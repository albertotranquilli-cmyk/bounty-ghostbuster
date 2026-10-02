"""Replays real GitHub responses recorded on 2026-10-02 (tests/fixtures/rec)."""
import os
from datetime import datetime, timezone

from ghostbuster.checks import check_issue, parse_ref, score
from ghostbuster.client import GitHub
from ghostbuster.report import to_markdown

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "rec")
NOW = datetime(2026, 10, 2, 15, 15, tzinfo=timezone.utc)
gh = GitHub(replay_dir=FIX)


def test_struck_bounty_is_phantom():
    r = check_issue(gh, "trpc/trpc", 4306, now=NOW)
    assert r["verdict"] == "PHANTOM" and "cancelled_struck" in r["flags"]
    assert r["usd"] == 50.0


def test_awarded_but_open_is_phantom():
    r = check_issue(gh, "PiLab-Indonesia/RPi-Monitoring", 12, now=NOW)
    assert r["verdict"] == "PHANTOM" and "already_paid" in r["flags"]


def test_deleted_repo_is_phantom():
    r = check_issue(gh, "buape/kiai-bounties", 1, now=NOW)
    assert r["verdict"] == "PHANTOM" and "repo_gone" in r["flags"]


def test_swarmed_issue_flags_competition():
    r = check_issue(gh, "lablab-ai/community-content", 462, now=NOW)
    assert "swarmed" in r["flags"] and "competing_prs" in r["flags"]
    assert r["open_prs"] >= 2


def test_score_formula_and_report():
    res = {"usd": 100.0, "platform": "algora", "flags": {}, "open_prs": 1, "claimants": 0, "effort": "S"}
    s = score(res)
    assert s["EV_h"] == round(100 * 0.8 * 0.5 * 0.5 * 0.8 / 4, 2)
    assert set(s["why"]) == {"P_V", "P_A", "P_C", "P_P", "T"}
    md = to_markdown({"generated": "x", "source": "y"}, [check_issue(gh, "trpc/trpc", 4306, now=NOW)])
    assert "PHANTOM" in md and "cancelled_struck" in md


def test_parse_ref():
    assert parse_ref("a/b#3") == ("a/b", 3)
    assert parse_ref("https://github.com/a/b.c/issues/7") == ("a/b.c", 7)


def test_fixtures_contain_no_credentials():
    import re
    for f in os.listdir(FIX):
        txt = open(os.path.join(FIX, f)).read()
        assert not re.search(r"gh[opsu]_[A-Za-z0-9]{20,}|github_pat_", txt), f


def test_gate_api_and_cli(capsys):
    import json

    from ghostbuster import gate
    from ghostbuster.cli import main
    d = gate("trpc/trpc", 4306, gh=gh)
    assert d["verdict"] == "PHANTOM" and d["go"] is False and "cancelled_struck" in d["reasons"]
    assert d["amount_usd"] == 50.0
    rc = main(["gate", "buape/kiai-bounties#1", "--json", "--replay", FIX])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["verdict"] == "PHANTOM" and "repo_gone" in out["reasons"]
