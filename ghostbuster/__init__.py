"""bounty-ghostbuster: verify GitHub bounty issues against live state and flag phantoms."""
__version__ = "0.1.0"


def gate(repo: str, issue_number: int, gh=None, check_policy: bool = True) -> dict:
    """Single anti-phantom gate. Returns a compact, JSON-serialisable decision:

    {ref, url, verdict: PHANTOM|RISKY|LIVE, go: bool, reasons: {flag: evidence}, amount_usd,
     platform, P: {P_V, P_A, P_C, P_P}, T_hours, EV_h, why: {...}, open_prs, claimants}

    `go` is True only for LIVE verdicts with EV/h >= 3.0 (same threshold as the prior arb scan).
    Read-only: GET requests only (token from GITHUB_TOKEN/GH_TOKEN or `gh auth token`).
    """
    from .checks import check_issue
    from .client import GitHub

    r = check_issue(gh or GitHub(), repo, int(issue_number), check_policy=check_policy)
    s = r.get("score") or {}
    return {
        "ref": r["ref"], "url": r["url"], "title": r.get("title"), "verdict": r["verdict"],
        "go": r["verdict"] == "LIVE" and (s.get("EV_h") or 0) >= 3.0,
        "reasons": r["flags"], "amount_usd": r.get("usd"), "platform": r.get("platform"),
        "P": {k: s.get(k) for k in ("P_V", "P_A", "P_C", "P_P")} if s else None,
        "T_hours": s.get("T"), "EV_h": s.get("EV_h"), "why": s.get("why"),
        "open_prs": r.get("open_prs"), "claimants": r.get("claimants"), "effort": r.get("effort"),
    }
