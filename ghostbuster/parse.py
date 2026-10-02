"""Pure parsing helpers: bounty markers in comments, labels and multilingual text."""
from __future__ import annotations

import re

AMOUNT = r"([0-9][0-9,]*(?:\.\d+)?k?)"


def usd(s: str) -> float:
    s = s.replace(",", "")
    return float(s[:-1]) * 1000 if s.lower().endswith("k") else float(s)


# Multilingual bounty keywords (EN/ZH/RU/ES/PT/JA/KO).
BOUNTY_WORDS = {
    "en": r"\bbount(y|ies)\b|\breward\b",
    "zh": r"赏金|悬赏|奖金",
    "ru": r"вознагражден|баунти|награда",
    "es": r"\brecompensa\b",
    "pt": r"\brecompensa\b|\bprêmio\b",
    "ja": r"報奨金|懸賞金|バウンティ",
    "ko": r"현상금|포상금|바운티",
}
BOUNTY_LABEL = re.compile(r"bounty|💎|reward|赏金|悬赏|现金|報奨|현상금|recompensa", re.I)
PAID_LABEL = re.compile(r"\b(rewarded|paid|awarded|bounty[- ]?(paid|claimed|done|closed))\b|已支付|已发放", re.I)
MONEY = re.compile(r"(?:US)?\$\s?" + AMOUNT + r"|" + AMOUNT + r"\s?(?:USD|美元|долл)", re.I)

AI_BAN = re.compile(
    r"(no|not accept\w*|reject\w*|ban\w*|prohibit\w*|forbid\w*|disallow\w*|won'?t accept|will be closed|"
    r"do not (submit|open|use)|don'?t (submit|use))[^.\n]{0,80}\b(AI|A\.I\.|LLM|ChatGPT|Copilot|Claude|GPT|"
    r"machine[- ]generated|AI[- ]generated|AI[- ]assisted|agentic|vibe[- ]cod)", re.I)
AI_BAN2 = re.compile(
    r"\b(AI|LLM|machine)[- ](generated|written|authored|assisted)[^.\n]{0,60}(not (be )?(accepted|allowed|"
    r"welcome|permitted)|rejected|closed|banned|prohibited|forbidden)", re.I)

ALGORA_AMT = re.compile(r"💎\s*(~~)?\s*\*{0,2}\$" + AMOUNT + r"\*{0,2}\s*(~~)?\s*bounty")


def languages(text: str) -> list[str]:
    return [lang for lang, rx in BOUNTY_WORDS.items() if re.search(rx, text or "", re.I)]


def parse_comments(comments: list[dict]) -> dict:
    """Extract bounty state from issue comments (Algora + Opire bot formats + slash commands)."""
    r = {"amounts": [], "struck": False, "awarded": [], "attempts": [], "claims": [],
         "bounty_at": None, "bot_url": None, "maint_last": None, "platform": None}
    for cm in comments:
        b = cm.get("body") or ""
        u = (cm.get("user") or {}).get("login", "")
        if u.startswith("algora-pbc"):
            r["platform"] = "algora"
            m = ALGORA_AMT.search(b)
            if m:
                r["amounts"].append(usd(m.group(2)))
                r["bounty_at"] = r["bounty_at"] or cm.get("created_at")
                r["bot_url"] = cm.get("html_url")
                if (m.group(1) or m.group(3) or b.lstrip().startswith("~~") or "~~💎" in b
                        or re.search(r"~~[^~\n]*\$[0-9][^~\n]*~~", b)):
                    r["struck"] = True
            if re.search(r"has been awarded|🎉🎈", b, re.I):
                a = re.search(r"\$" + AMOUNT, b)
                r["awarded"].append({"amt": usd(a.group(1)) if a else None, "url": cm.get("html_url")})
        elif u.startswith("opirebot"):
            r["platform"] = r["platform"] or "opire"
            m = re.search(r"created a \$" + AMOUNT + " reward", b)
            if m:
                r["amounts"].append(usd(m.group(1)))
                r["bounty_at"] = r["bounty_at"] or cm.get("created_at")
                r["bot_url"] = cm.get("html_url")
            if re.search(r"completed the payment of \$", b) and "as a tip" not in b:
                r["awarded"].append({"amt": None, "url": cm.get("html_url")})
        else:
            if re.search(r"(^|\s)/(attempt|try)\b", b):
                r["attempts"].append({"user": u, "at": cm.get("created_at")})
            if re.search(r"(^|\s)/claim\b", b):
                r["claims"].append({"user": u, "at": cm.get("created_at")})
            if cm.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR") and not u.endswith("[bot]"):
                r["maint_last"] = cm.get("created_at")
    return r


def amount_from_text(text: str) -> float | None:
    """Best-effort amount from title/body when no bot comment exists (only if a bounty keyword is present)."""
    if not languages(text):
        return None
    vals = [usd(a or b) for a, b in MONEY.findall(text or "") if (a or b)]
    vals = [v for v in vals if 1 <= v <= 100000]
    return max(vals) if vals else None


def struck_text_amount(text: str) -> bool:
    return bool(re.search(r"~~[^~\n]*\$\s?[0-9][^~\n]*~~", text or ""))


def ai_ban_lines(text: str) -> list[str]:
    return [ln.strip()[:160] for ln in (text or "").splitlines() if AI_BAN.search(ln) or AI_BAN2.search(ln)]
