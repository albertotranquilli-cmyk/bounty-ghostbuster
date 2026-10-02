from ghostbuster import parse


def c(login, body, assoc="NONE", at="2026-01-01T00:00:00Z"):
    return {"user": {"login": login}, "body": body, "author_association": assoc, "created_at": at,
            "html_url": "https://github.com/o/r/issues/1#c"}


def test_algora_live_amount():
    r = parse.parse_comments([c("algora-pbc[bot]", "## 💎 $250 bounty [• Acme](https://algora.io/acme)")])
    assert r["amounts"] == [250.0] and not r["struck"] and r["platform"] == "algora"


def test_algora_struck_is_cancelled():
    r = parse.parse_comments([c("algora-pbc[bot]", "## ~~💎 $50 bounty~~")])
    assert r["struck"]


def test_awarded_and_attempts():
    r = parse.parse_comments([
        c("algora-pbc[bot]", "💎 **$1.5k** bounty"),
        c("alice", "/attempt #1"), c("bob", "/attempt"), c("carol", "/claim #9"),
        c("algora-pbc[bot]", "🎉🎈 @alice has been awarded **$1.5k**! 🎈🎊"),
    ])
    assert r["amounts"] == [1500.0]
    assert len(r["attempts"]) == 2 and len(r["claims"]) == 1
    assert r["awarded"] and r["awarded"][0]["amt"] == 1500.0


def test_multilingual_keywords():
    assert parse.languages("修复这个 bug 赏金 $100") == ["en", "zh"] or "zh" in parse.languages("赏金 $100")
    assert "ru" in parse.languages("Вознаграждение 50$")
    assert "ja" in parse.languages("報奨金あり")
    assert "ko" in parse.languages("현상금 $30")
    assert "es" in parse.languages("Recompensa de $40")
    assert parse.amount_from_text("悬赏 200 USD 修复") == 200.0
    assert parse.amount_from_text("costs $40 to host") is None  # no bounty keyword -> no amount


def test_paid_label_and_ai_ban():
    assert parse.PAID_LABEL.search("💎 Rewarded")
    assert not parse.PAID_LABEL.search("💎 Bounty")
    assert parse.ai_ban_lines("We do not accept AI-generated pull requests.\nBe nice.")
    assert not parse.ai_ban_lines("AI usage is allowed if you understand the change.")
