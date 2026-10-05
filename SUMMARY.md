# bounty-ghostbuster — one-page summary

**The problem:** most "open" GitHub bounties are ghosts. Contributors spend weekends on issues that are already awarded, cancelled, or in archived repos.

**What we measured (scan of 2026-10-02):**
- Algora listed 371 bounties. After filtering: 174 non-spam, 81 with a live marker ≥$20, 31 open+unlocked+unassigned+recent, 9 confirmed live by Algora's own data, **1 fresh, 0 uncontested**.
- 38 issues were still open after the bot announced the bounty had been awarded.
- Opire's API listed 6 available rewards totalling $212; GitHub showed 113 ghost issues with Opire reward traffic but no available reward.
- 114 open PRs pointed at phantom bounties — roughly 456 contributor-hours of unpaid work (at 4h per attempt).

**What the tool does (v0.1, read-only, MIT):**
- `ghostbuster scan` checks bounty issues against live GitHub state and flags phantoms: repo gone, issue deleted/closed, already paid, cancelled (struck-through amount), merged fix, no bounty marker, swarmed (5+ claimants), AI-banned, stale.
- Ranks survivors by expected dollars per hour, with a one-line justification for every factor.
- `ghostbuster gate owner/repo#N` — single-issue check for bots and watchers; exit code 2 = PHANTOM.
- `ghostbuster hygiene --org X` — audits a funding org's own bounty issues and estimates wasted contributor hours.
- Ships as a CLI and a GitHub Action you can drop into any repo.

**Install:** `pip install git+https://github.com/albertotranquilli-cmyk/bounty-ghostbuster`

**Limits:** heuristics can be wrong — always read the issue. v0.1 does not query Algora's or Opire's own APIs (planned Pro feature).

Link: https://github.com/albertotranquilli-cmyk/bounty-ghostbuster