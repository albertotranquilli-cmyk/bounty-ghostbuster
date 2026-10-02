"""Live verification of a single bounty issue. Produces flags, verdict and EV/h score."""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

from . import parse
from .client import GitHub

# Flag -> severity. PHANTOM flags mean the bounty is (almost certainly) not collectable.
PHANTOM_FLAGS = {"repo_gone", "issue_deleted", "issue_closed", "is_pull_request", "repo_archived",
                 "already_paid", "cancelled_struck", "merged_fix", "no_bounty_marker"}
RISK_FLAGS = {"repo_redirected", "issue_locked", "assigned", "swarmed", "competing_prs",
              "ai_banned", "stale_repo", "stale_bounty"}

CONTRIB_FILES = ["CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", "AI_POLICY.md"]
T_HOURS = {"S": 4.0, "M": 10.0, "L": 24.0}
EFFORT_L = re.compile(r"\b(implement(ation)?|new (feature|backend|provider|integration|plugin)|support for|rewrite|"
                      r"migrat\w+|port(ing)? to|refactor|architecture|end-to-end|e2e|design|performance|optimi[sz]\w+)\b", re.I)
EFFORT_S = re.compile(r"\b(typo|docs?|documentation|readme|rename|link|crash|panic|exception|regression|wrong|"
                      r"incorrect|error message|missing|null|undefined|flag|option|bump)\b", re.I)


def _days(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    return (now - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds() / 86400


def parse_ref(ref: str) -> tuple[str, int]:
    m = re.match(r"(?:https://github\.com/)?([\w.-]+/[\w.-]+)(?:#|/issues/)(\d+)$", ref.strip())
    if not m:
        raise ValueError(f"bad issue ref: {ref!r} (want owner/repo#N)")
    return m.group(1), int(m.group(2))


def effort(title: str, body: str, amt: float) -> str:
    text = f"{title}\n{body}"
    score = min(len(EFFORT_L.findall(text)), 4) - min(len(EFFORT_S.findall(text)), 3)
    score += (len(body) > 3000) + (body.count("- [ ]") >= 4) + (2 if amt >= 500 else 1 if amt >= 150 else 0)
    return "S" if score <= 0 else "M" if score <= 2 else "L"


def check_issue(gh: GitHub, repo: str, number: int, now: datetime | None = None,
                ci_limit: int = 3, check_policy: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    res: dict = {"ref": f"{repo}#{number}", "url": f"https://github.com/{repo}/issues/{number}",
                 "flags": {}, "title": None, "usd": None, "platform": None}
    flags = res["flags"]

    st, r = gh.get(f"repos/{repo}")
    if st != 200 or not isinstance(r, dict):
        flags["repo_gone"] = f"GET repos/{repo} -> HTTP {st} (deleted, private or renamed away)"
        return finalize(res, now)
    full = r["full_name"]
    if full.lower() != repo.lower():
        flags["repo_redirected"] = f"{repo} now redirects to {full}"
    if r.get("archived"):
        flags["repo_archived"] = f"{full} is archived (read-only: no PR can be merged)"
    res["repo"] = {"full_name": full, "stars": r.get("stargazers_count"), "language": r.get("language"),
                   "pushed_at": r.get("pushed_at")}
    pd = _days(r.get("pushed_at"), now)
    if pd is not None and pd > 90:
        flags["stale_repo"] = f"last push {pd:.0f} days ago"

    st, iss = gh.get(f"repos/{full}/issues/{number}")
    if st in (404, 410) or not isinstance(iss, dict):
        flags["issue_deleted"] = f"GET issue -> HTTP {st}"
        return finalize(res, now)
    res["title"] = iss.get("title")
    res["url"] = iss.get("html_url", res["url"])
    if iss.get("pull_request"):
        flags["is_pull_request"] = "listing points at a pull request, not an issue"
    if iss.get("state") == "closed":
        flags["issue_closed"] = f"closed ({iss.get('state_reason') or 'unspecified'}) at {iss.get('closed_at')}"
    if iss.get("locked"):
        flags["issue_locked"] = "conversation locked (cannot /attempt or discuss)"
    if iss.get("assignees"):
        flags["assigned"] = "assigned to " + ", ".join(a["login"] for a in iss["assignees"])
    labels = [l["name"] for l in iss.get("labels") or []]
    res["labels"] = labels
    paid_labels = [l for l in labels if parse.PAID_LABEL.search(l)]
    if paid_labels:
        flags["already_paid"] = f"label(s) {paid_labels} say the bounty was paid/rewarded"

    comments = gh.pages(f"repos/{full}/issues/{number}/comments", 3) if iss.get("comments") else []
    pc = parse.parse_comments(comments)
    text = f"{iss.get('title') or ''}\n{iss.get('body') or ''}"
    res["languages"] = parse.languages(text)
    res["platform"] = pc["platform"] or ("label" if any(parse.BOUNTY_LABEL.search(l) for l in labels) else
                                         "text" if res["languages"] else None)
    if pc["awarded"]:
        flags["already_paid"] = f"bot announced award/payment but issue still listed: {pc['awarded'][0]['url']}"
    if pc["struck"] or parse.struck_text_amount(iss.get("body") or ""):
        flags["cancelled_struck"] = f"bounty amount struck through (~~$X~~ = cancelled): {pc['bot_url'] or res['url']}"
    amt = max(pc["amounts"]) if pc["amounts"] else parse.amount_from_text(text)
    res["usd"] = amt
    res["amount_source"] = pc["bot_url"] or ("issue title/body" if amt else None)
    if amt is None and not res["platform"]:
        flags["no_bounty_marker"] = "no bounty bot comment, bounty label or bounty keyword+amount found"
    ba = _days(pc["bounty_at"], now)
    ml = _days(pc["maint_last"], now)
    if ba is not None and ba > 365 and (ml is None or ml > 90):
        flags["stale_bounty"] = f"bounty posted {ba:.0f}d ago; last maintainer comment " + (f"{ml:.0f}d ago" if ml else "never")
    attempts = {a["user"] for a in pc["attempts"]} | {c["user"] for c in pc["claims"]}
    res["attempts"] = len(pc["attempts"])
    res["claimants"] = len(attempts)
    if len(attempts) >= 5:
        flags["swarmed"] = f"{len(attempts)} distinct users posted /attempt or /claim"

    # competing PRs from the timeline
    tl = gh.pages(f"repos/{full}/issues/{number}/timeline", 3)
    prs = {}
    for e in tl:
        if e.get("event") != "cross-referenced":
            continue
        s = (e.get("source") or {}).get("issue") or {}
        if not s.get("pull_request"):
            continue
        rp = s["repository_url"].split("repos/")[1]
        prs[f"{rp}#{s['number']}"] = {"repo": rp, "n": s["number"], "state": s["state"],
                                      "merged": bool(s["pull_request"].get("merged_at")),
                                      "user": (s.get("user") or {}).get("login"), "created": s.get("created_at")}
    prs_l = list(prs.values())
    same = [p for p in prs_l if p["repo"].lower() == full.lower()]
    merged = [p for p in same if p["merged"]]
    open_prs = [p for p in same if p["state"] == "open"]
    if merged:
        flags["merged_fix"] = "same-repo PR already merged: " + ", ".join(f"#{p['n']}" for p in merged)
    for p in sorted(open_prs, key=lambda p: p["created"] or "", reverse=True)[:ci_limit]:
        p["ci"] = pr_ci(gh, p)
    if len(open_prs) >= 2:
        green = sum(1 for p in open_prs if p.get("ci") == "green")
        flags["competing_prs"] = f"{len(open_prs)} open same-repo PRs reference it ({green} with green CI among checked)"
    res["prs"] = prs_l
    res["open_prs"] = len(open_prs)

    if check_policy and not (PHANTOM_FLAGS & set(flags)):
        hits = []
        for f in CONTRIB_FILES:
            st, d = gh.get(f"repos/{full}/contents/{f}")
            if st == 200 and isinstance(d, dict) and d.get("content"):
                t = base64.b64decode(d["content"]).decode("utf8", "ignore")
                hits += [f"{f}: {h}" for h in parse.ai_ban_lines(t)]
        if hits:
            flags["ai_banned"] = hits[0]
    res["effort"] = effort(iss.get("title") or "", iss.get("body") or "", amt or 0)
    return finalize(res, now)


def pr_ci(gh: GitHub, pr: dict) -> str | None:
    st, d = gh.get(f"repos/{pr['repo']}/pulls/{pr['n']}")
    if st != 200 or not isinstance(d, dict):
        return None
    st, c = gh.get(f"repos/{pr['repo']}/commits/{d['head']['sha']}/check-runs?per_page=100")
    if st != 200 or not isinstance(c, dict):
        return None
    concl = [x.get("conclusion") or x.get("status") for x in c.get("check_runs", [])]
    if any(x in ("failure", "timed_out", "cancelled", "action_required") for x in concl):
        return "fail"
    if any(x in ("queued", "in_progress", None) for x in concl):
        return "pending"
    return "green" if concl else "none"


def finalize(res: dict, now: datetime) -> dict:
    f = set(res["flags"])
    res["verdict"] = "PHANTOM" if f & PHANTOM_FLAGS else "RISKY" if f & RISK_FLAGS else "LIVE"
    res["score"] = score(res) if res["verdict"] != "PHANTOM" else None
    return res


def score(res: dict) -> dict:
    """EV/h = B * P_V * P_A * P_C * P_P / T, each factor with a written justification."""
    f, J = res["flags"], {}
    B = res.get("usd") or 0.0
    if res.get("platform") == "algora" or res.get("platform") == "opire":
        pv = 0.8
        J["P_V"] = f"{res['platform']} bot comment shows ${B:,.0f}, not struck, no award announced"
    elif B:
        pv = 0.5
        J["P_V"] = f"amount ${B:,.0f} only stated in issue text/label (no platform escrow evidence)"
    else:
        pv = 0.2
        J["P_V"] = "bounty label/keyword but no parseable amount"
    pa = 0.5
    why = ["baseline 0.5"]
    if "stale_repo" in f: pa *= 0.3; why.append("repo not pushed in >90d")
    if "stale_bounty" in f: pa *= 0.5; why.append("bounty >1y old with no recent maintainer comment")
    if "ai_banned" in f: pa *= 0.1; why.append("CONTRIBUTING bans AI-assisted PRs")
    if "issue_locked" in f or "assigned" in f: pa *= 0.3; why.append("locked/assigned")
    J["P_A"] = "; ".join(why)
    n_open, n_att = res.get("open_prs") or 0, res.get("claimants") or 0
    pc = round(1 / (1 + n_open + 0.15 * n_att), 2)
    J["P_C"] = f"1/(1 + {n_open} open PRs + 0.15×{n_att} claimants)"
    pp = 0.8 if res.get("platform") == "algora" else 0.6 if res.get("platform") == "opire" else 0.4
    J["P_P"] = {"algora": "Algora: maintainer pays via platform on merge (not pre-escrowed)",
                "opire": "Opire: creator pays manually after claim"}.get(res.get("platform"), "self-declared bounty, no platform")
    T = T_HOURS[res.get("effort") or "M"]
    J["T"] = f"effort {res.get('effort') or 'M'} -> {T:.0f}h (repro + patch + tests + green CI)"
    ev = B * pv * pa * pc * pp / T
    return {"B": B, "P_V": pv, "P_A": round(pa, 3), "P_C": pc, "P_P": pp, "T": T, "EV_h": round(ev, 2), "why": J}
