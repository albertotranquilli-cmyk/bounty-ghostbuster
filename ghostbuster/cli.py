"""`ghostbuster scan --query ... | --issue owner/repo#N`"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import __version__
from .checks import check_issue, parse_ref
from .client import GitHub
from .report import to_json, to_markdown

DEFAULT_QUERY = "commenter:app/algora-pbc is:issue is:open"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ghostbuster", description="Anti-phantom GitHub bounty scanner (read-only).")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="verify bounty issues against live GitHub state")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--query", help=f"GitHub issue search query (e.g. '{DEFAULT_QUERY}')")
    g.add_argument("--issue", action="append", help="owner/repo#N (repeatable)")
    s.add_argument("--limit", type=int, default=30, help="max issues to verify from a query (default 30)")
    s.add_argument("--format", choices=["md", "json"], default="md")
    s.add_argument("-o", "--output", help="write report to file (default stdout)")
    s.add_argument("--json-output", help="additionally write the JSON report to this file")
    s.add_argument("--record", help="record API responses as test fixtures into DIR")
    s.add_argument("--replay", help="replay API responses from fixture DIR (offline)")
    s.add_argument("--no-policy", action="store_true", help="skip CONTRIBUTING AI-policy check")
    h = sub.add_parser("hygiene", help="org-level bounty hygiene audit (for bounty-funding orgs)")
    h.add_argument("--org", action="append", required=True, help="GitHub org/user (repeatable)")
    h.add_argument("--limit", type=int, default=60)
    h.add_argument("--no-platform", action="store_true", help="skip public algora.io cross-checks")
    h.add_argument("-o", "--output-dir", default=".", help="directory for <org>.md/.json reports")
    gp = sub.add_parser("gate", help="single-issue anti-phantom gate decision")
    gp.add_argument("ref", help="owner/repo#N")
    gp.add_argument("--json", action="store_true", help="print JSON (default: one-line summary)")
    gp.add_argument("--replay", help="replay fixtures DIR (offline)")
    a = ap.parse_args(argv)
    if a.cmd == "gate":
        import json

        from . import gate
        repo, n = parse_ref(a.ref)
        d = gate(repo, n, gh=GitHub(replay_dir=a.replay) if a.replay else None)
        if a.json:
            print(json.dumps(d, indent=1, default=str))
        else:
            print(f"{d['ref']} {d['verdict']} go={d['go']} ${d['amount_usd']} EV/h={d['EV_h']} reasons={list(d['reasons'])}")
        return 0 if d["verdict"] != "PHANTOM" else 2
    if a.cmd == "hygiene":
        return _hygiene(a)

    gh = GitHub(record_dir=a.record, replay_dir=a.replay)
    refs: list[tuple[str, int]] = []
    meta = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "version": __version__}
    if a.issue:
        refs = [parse_ref(x) for x in a.issue]
        meta["source"] = " ".join(a.issue)
    else:
        total, items = gh.search_issues(a.query, a.limit)
        meta["source"], meta["search_total"] = a.query, total
        refs = [(it["repository_url"].split("repos/")[1], it["number"]) for it in items]
    results = []
    for i, (repo, n) in enumerate(refs, 1):
        print(f"[{i}/{len(refs)}] {repo}#{n}", file=sys.stderr, flush=True)
        try:
            results.append(check_issue(gh, repo, n, check_policy=not a.no_policy))
        except Exception as e:  # keep scanning; report the error
            results.append({"ref": f"{repo}#{n}", "url": f"https://github.com/{repo}/issues/{n}", "flags": {"error": str(e)},
                            "verdict": "RISKY", "score": None})
    meta["api_calls"] = gh.calls
    out = to_json(meta, results) if a.format == "json" else to_markdown(meta, results)
    if a.json_output:
        open(a.json_output, "w").write(to_json(meta, results))
    if a.output:
        open(a.output, "w").write(out)
    else:
        sys.stdout.write(out)
    return 0


def _hygiene(a) -> int:
    import json
    import os

    from .hygiene import audit_org
    from .hygiene import to_markdown as hmd
    os.makedirs(a.output_dir, exist_ok=True)
    for org in a.org:
        print(f"[hygiene] {org}", file=sys.stderr, flush=True)
        gh = GitHub()
        res = audit_org(gh, org, a.limit, platform=not a.no_platform)
        open(os.path.join(a.output_dir, f"{org}.md"), "w").write(hmd(res))
        open(os.path.join(a.output_dir, f"{org}.json"), "w").write(json.dumps(res, indent=1, default=str))
        print(json.dumps(res["summary"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
