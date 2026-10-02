from datetime import datetime, timezone

from ghostbuster import hygiene

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


class FakeGH:
    calls = 0

    def __init__(self, comments, timeline):
        self.c, self.t = comments, timeline

    def pages(self, path, maxpages=3):
        return self.c if path.endswith("/comments") else self.t

    def search_issues(self, q, limit):
        return 1, [ITEM]


def cm(login, body, at="2024-01-01T00:00:00Z"):
    return {"user": {"login": login}, "body": body, "created_at": at, "html_url": "u", "author_association": "NONE"}


ITEM = {"repository_url": "https://api.github.com/repos/acme/app", "number": 7, "html_url": "https://github.com/acme/app/issues/7",
        "title": "[$100] fix crash", "locked": True, "comments": 3, "labels": [{"name": "💎 Bounty"}]}
PR = {"event": "cross-referenced", "source": {"issue": {"number": 9, "state": "open", "pull_request": {"merged_at": None},
                                                        "repository_url": "https://api.github.com/repos/acme/app"}}}


def no_web(url):
    return 404, ""


def test_awarded_open_is_phantom_and_counts_wasted_hours():
    gh = FakeGH([cm("algora-pbc[bot]", "💎 $50 bounty"), cm("a", "/attempt"),
                 cm("algora-pbc[bot]", "🎉🎈 @a has been awarded $50")], [PR])
    res = hygiene.audit_org(gh, "acme", now=NOW, fetch=no_web)
    s = res["summary"]
    assert s["awarded_but_open"] == 1 and s["phantoms"] == 1
    assert s["open_prs_on_phantoms"] == 1 and s["est_hours_wasted"] == hygiene.HOURS_PER_PR
    # title says $100, bot says $50
    assert s["amount_mismatch"] == 1


def test_stale_locked_live_bounty():
    gh = FakeGH([cm("algora-pbc[bot]", "💎 $100 bounty"), cm("a", "/attempt"), cm("b", "/attempt")], [])
    s = hygiene.audit_org(gh, "acme", now=NOW, fetch=no_web)["summary"]
    assert s["stale_bounties"] == 1 and s["stale_swarm_claimants"] == 2 and s["locked_live"] == 1
    assert s["phantoms"] == 0


def test_algora_shields_parse():
    fetch = lambda url: (200, '{"message": "$1,250"}')
    assert hygiene.algora_org_totals("acme", fetch) == {"open": 1250.0, "completed": 1250.0}


def test_archived_repo_makes_bounty_phantom():
    class ArchGH(FakeGH):
        def get(self, path):
            return 200, {"archived": True}
    gh = ArchGH([cm("algora-pbc[bot]", "💎 $100 bounty")], [PR])
    s = hygiene.audit_org(gh, "acme", now=NOW, fetch=no_web)["summary"]
    assert s["archived_repo_bounties"] == 1 and s["phantoms"] == 1 and s["locked_live"] == 0
    assert s["open_prs_on_phantoms"] == 1
