"""Org-level bounty hygiene audit (read-only).

For an org that funds bounties: open issues that were already awarded/paid, amount mismatches
(bot comment vs. issue title/labels vs. Algora's public ticket page), stale bounties with swarm
counts, locked issues with live bounties, and an estimate of contributor hours spent on phantoms.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone

from . import parse
from .client import GitHub

HOURS_PER_PR = 4.0  # assumption: one open PR ~= 4h of contributor work (repro + patch + tests)


def _days(ts, now):
    return None if not ts else (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 86400


def _web(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "bounty-ghostbuster/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf8", "ignore")
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", 0) or 0, ""


def algora_org_totals(org: str, fetch=_web) -> dict:
    out = {}
    for k in ("open", "completed"):
        st, body = fetch(f"https://algora.io/api/shields/{org}/bounties?status={k}")
        try:
            out[k] = float(re.sub(r"[^0-9.]", "", json.loads(body).get("message", "")) or 0) if st == 200 else None
        except Exception:  # noqa: BLE001
            out[k] = None
    return out


def algora_ticket_amount(full: str, n: int, fetch=_web) -> float | None:
    st, h = fetch(f"https://algora.io/{full}/issues/{n}")
    if st != 200 or not h:
        return None
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t))
    m = re.search(r"#%d \$([0-9][0-9,]*(?:\.\d+)?k?) " % n, t)
    return parse.usd(m.group(1)) if m else None


def _title_label_amounts(item: dict) -> list[float]:
    txt = item.get("title", "") + " " + " ".join(l["name"] for l in item.get("labels") or [])
    return [parse.usd(a) for a in re.findall(r"\$\s?([0-9][0-9,]*(?:\.\d+)?k?)", txt)]


def apply_archived(r: dict, archived: bool) -> None:
    """Archived repo: nothing can be merged, so any advertised bounty is a phantom."""
    if archived and not any(k == "repo_archived" for k, _ in r["issues"]):
        r["issues"] = [x for x in r["issues"] if x[0] != "locked_live"]  # archived implies locked; report the root cause
        r["issues"].insert(0, ("repo_archived", "repository is archived; bounty can never be merged/paid"))
        r["phantom"] = True


def audit_issue(gh: GitHub, item: dict, now: datetime, platform: bool = True, fetch=_web) -> dict:
    full = item["repository_url"].split("repos/")[1]
    n = item["number"]
    cs = gh.pages(f"repos/{full}/issues/{n}/comments", 3) if item.get("comments") else []
    pc = parse.parse_comments(cs)
    labels = [l["name"] for l in item.get("labels") or []]
    r = {"ref": f"{full}#{n}", "url": item["html_url"], "title": item["title"], "locked": item.get("locked"),
         "labels": labels, "bot_usd": max(pc["amounts"]) if pc["amounts"] else None, "struck": pc["struck"],
         "awarded": pc["awarded"], "claimants": len({a["user"] for a in pc["attempts"] + pc["claims"]}),
         "bounty_age_d": _days(pc["bounty_at"], now), "maint_last": pc["maint_last"], "issues": []}
    tl = gh.pages(f"repos/{full}/issues/{n}/timeline", 2)
    prs = {}
    for e in tl:
        s = (e.get("source") or {}).get("issue") or {}
        if e.get("event") == "cross-referenced" and s.get("pull_request"):
            rp = s["repository_url"].split("repos/")[1]
            if rp.lower() == full.lower():
                prs[s["number"]] = {"state": s["state"], "merged": bool(s["pull_request"].get("merged_at"))}
    r["open_prs"] = sum(1 for p in prs.values() if p["state"] == "open")
    r["merged_prs"] = sum(1 for p in prs.values() if p["merged"])
    bounty_label = [l for l in labels if parse.BOUNTY_LABEL.search(l) and not parse.PAID_LABEL.search(l)]
    if pc["awarded"]:
        r["issues"].append(("awarded_but_open", f"awarded {pc['awarded'][0]['url']} but issue still open"
                            + (f"; still labelled {bounty_label}" if bounty_label else "")))
    tl_amts = _title_label_amounts(item)
    if r["bot_usd"] is not None:
        if tl_amts and all(abs(a - r["bot_usd"]) > 0.5 for a in tl_amts):
            r["issues"].append(("amount_mismatch", f"bot ${r['bot_usd']:,.0f} vs title/label {tl_amts}"))
        if platform and not pc["struck"] and not pc["awarded"]:
            tk = algora_ticket_amount(full, n, fetch)
            r["ticket_usd"] = tk
            if tk is not None and abs(tk - r["bot_usd"]) > 0.5:
                r["issues"].append(("amount_mismatch", f"bot comment ${r['bot_usd']:,.0f} vs algora.io ticket page ${tk:,.0f}"))
    live = r["bot_usd"] is not None and not pc["struck"] and not pc["awarded"]
    if live and r["bounty_age_d"] and r["bounty_age_d"] > 365:
        r["issues"].append(("stale_bounty", f"{r['bounty_age_d']:.0f}d old, {r['claimants']} claimants, {r['open_prs']} open PRs"))
    if live and item.get("locked"):
        r["issues"].append(("locked_live", "issue locked while bounty still advertised"))
    if pc["struck"]:
        r["issues"].append(("cancelled_open", "bounty struck through (cancelled) but issue still open"))
    if live and r["merged_prs"]:
        r["issues"].append(("merged_but_unpaid_or_open", f"{r['merged_prs']} same-repo PR(s) merged, bounty still shown live"))
    r["phantom"] = bool(pc["awarded"] or pc["struck"] or (live and r["merged_prs"]))
    return r


def audit_org(gh: GitHub, org: str, limit: int = 60, platform: bool = True, now: datetime | None = None,
              fetch=_web) -> dict:
    now = now or datetime.now(timezone.utc)
    total, items = gh.search_issues(f"org:{org} commenter:app/algora-pbc is:issue is:open", limit)
    items = [i for i in items if "pull_request" not in i]
    rows = [audit_issue(gh, it, now, platform, fetch) for it in items]
    archived: dict[str, bool] = {}
    for r in rows:
        full = r["ref"].split("#")[0]
        if full not in archived:
            st, ri = gh.get(f"repos/{full}") if hasattr(gh, "get") else (0, None)
            archived[full] = bool(st == 200 and isinstance(ri, dict) and ri.get("archived"))
        apply_archived(r, archived[full])
    totals = algora_org_totals(org, fetch) if platform else {}
    live_usd = sum(r["bot_usd"] or 0 for r in rows if r["bot_usd"] and not r["phantom"] and not r["struck"])
    if platform and totals.get("open") is not None and live_usd > totals["open"] + 0.5:
        # GitHub advertises more than Algora's DB says is open for this org
        for r in rows:
            if r["bot_usd"] and not r["phantom"]:
                r["issues"].append(("platform_not_live", f"org GitHub-advertised ${live_usd:,.0f} > Algora open total ${totals['open']:,.0f}"))
                r["platform_doubt"] = True
    summary = summarize(org, total, rows, totals, live_usd, gh.calls)
    return {"summary": summary, "rows": rows, "totals": totals, "generated": now.strftime("%Y-%m-%d %H:%M UTC")}


def to_markdown(a: dict) -> str:
    s = a["summary"]
    L = [f"# 🧹 Bounty hygiene: {s['org']}", "", f"Generated {a['generated']} · read-only (GET only) · "
         f"est. hours assume {HOURS_PER_PR:.0f}h per open PR", "", "| Metric | Value |", "|---|---|"]
    L += [f"| {k.replace('_', ' ')} | {v if not isinstance(v, float) else f'{v:,.0f}'} |" for k, v in s.items() if k != "org"]
    L += ["", "## Findings", "", "| Issue | Bot $ | Claimants | Open PRs | Problems |", "|---|---|---|---|---|"]
    for r in sorted(a["rows"], key=lambda r: (-len(r["issues"]), -(r["open_prs"]))):
        if not r["issues"]:
            continue
        probs = "<br>".join(f"`{k}`: {v}" for k, v in r["issues"])
        amt = f"${r['bot_usd']:,.0f}" if r["bot_usd"] else "?"
        L.append(f"| [{r['ref']}]({r['url']}) {r['title'][:50]} | {amt} | {r['claimants']} | {r['open_prs']} | {probs} |")
    clean = sum(1 for r in a["rows"] if not r["issues"])
    L += ["", f"{clean} audited issue(s) had no hygiene problems.", ""]
    return "\n".join(L)


def summarize(org: str, total: int, rows: list[dict], totals: dict, live_usd: float, calls: int) -> dict:
    has = lambda r, k: any(x == k for x, _ in r["issues"])
    ph = [r for r in rows if r["phantom"]]
    doubt = [r for r in rows if r.get("platform_doubt")]
    wasted_prs = sum(r["open_prs"] for r in ph)
    doubt_prs = sum(r["open_prs"] for r in doubt)
    return {
        "org": org, "open_bounty_issues_found": total, "audited": len(rows),
        "awarded_but_open": sum(has(r, "awarded_but_open") for r in rows),
        "cancelled_open": sum(bool(r["struck"]) for r in rows),
        "amount_mismatch": sum(has(r, "amount_mismatch") for r in rows),
        "stale_bounties": sum(has(r, "stale_bounty") for r in rows),
        "stale_swarm_claimants": sum(r["claimants"] for r in rows if has(r, "stale_bounty")),
        "locked_live": sum(has(r, "locked_live") for r in rows),
        "archived_repo_bounties": sum(has(r, "repo_archived") for r in rows),
        "phantoms": len(ph), "open_prs_on_phantoms": wasted_prs,
        "est_hours_wasted": wasted_prs * HOURS_PER_PR,
        "platform_not_live_issues": len(doubt), "open_prs_on_platform_not_live": doubt_prs,
        "est_hours_at_risk_platform_not_live": doubt_prs * HOURS_PER_PR,
        "github_advertised_live_usd": live_usd, "algora_open_usd": totals.get("open"),
        "algora_completed_usd": totals.get("completed"),
        "calls": calls,
    }
