"""Markdown / JSON rendering."""
from __future__ import annotations

import json
from collections import Counter


def funnel(results: list[dict]) -> dict:
    v = Counter(r["verdict"] for r in results)
    flags = Counter(f for r in results for f in r["flags"])
    return {"scanned": len(results), "phantom": v["PHANTOM"], "risky": v["RISKY"], "live": v["LIVE"],
            "flags": dict(flags.most_common())}


def to_json(meta: dict, results: list[dict]) -> str:
    return json.dumps({"meta": meta, "funnel": funnel(results), "results": results}, indent=1, default=str)


def to_markdown(meta: dict, results: list[dict]) -> str:
    F = funnel(results)
    n = F["scanned"] or 1
    L = ["# 👻 bounty-ghostbuster report", "",
         f"Generated {meta.get('generated')} · source: `{meta.get('source')}` · "
         f"{meta.get('api_calls', 0)} read-only GitHub API calls", "",
         "## Funnel", "", "| Stage | Count | Share |", "|---|---|---|",
         f"| Listed bounties scanned | {F['scanned']} | 100% |",
         f"| 👻 PHANTOM (not collectable) | {F['phantom']} | {100*F['phantom']/n:.0f}% |",
         f"| ⚠️ RISKY (collectable but contested/blocked) | {F['risky']} | {100*F['risky']/n:.0f}% |",
         f"| ✅ LIVE (no red flags) | {F['live']} | {100*F['live']/n:.0f}% |", ""]
    if meta.get("search_total") is not None:
        L.insert(4, f"Search matched {meta['search_total']} issues; scanned the {F['scanned']} most recently updated.\n")
    L += ["### Flags", "", "| Flag | Issues |", "|---|---|"]
    L += [f"| `{k}` | {v} |" for k, v in F["flags"].items()]
    L += ["", "## Ranked by EV/h (non-phantom)", "",
          "EV/h = B × P_V × P_A × P_C × P_P / T", "",
          "| Issue | $ | Verdict | EV/h | Justification |", "|---|---|---|---|---|"]
    alive = sorted([r for r in results if r.get("score")], key=lambda r: -r["score"]["EV_h"])
    for r in alive:
        s = r["score"]
        just = "<br>".join(f"{k}={s[k] if k != 'T' else s['T']}: {s['why'][k]}" for k in ("P_V", "P_A", "P_C", "P_P", "T"))
        flags = ", ".join(f"`{k}`" for k in r["flags"]) or "—"
        L.append(f"| [{r['ref']}]({r['url']}) {(r.get('title') or '')[:50]} | {_amt(r)} | {r['verdict']} ({flags}) | "
                 f"**{s['EV_h']}** | {just} |")
    if not alive:
        L.append("| — | — | — | — | nothing survived |")
    L += ["", "## Phantoms (evidence)", "", "| Issue | $ | Why it's a ghost |", "|---|---|---|"]
    for r in results:
        if r["verdict"] == "PHANTOM":
            why = "<br>".join(f"`{k}`: {v}" for k, v in r["flags"].items())
            L.append(f"| [{r['ref']}]({r['url']}) {(r.get('title') or '')[:50]} | {_amt(r)} | {why} |")
    L += ["", "_Read-only scan: GET requests only. No comments, PRs or forks were made._", ""]
    return "\n".join(L)


def _amt(r: dict) -> str:
    return f"${r['usd']:,.0f}" if r.get("usd") else "?"
