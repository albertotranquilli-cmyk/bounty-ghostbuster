# 👻 bounty-ghostbuster

**Most "open" GitHub bounties are ghosts. This tool tells you which ones before you spend a weekend on them.**

`bounty-ghostbuster` takes bounty issues (Algora bot comments, Opire bot comments, bounty labels, and bounty
keywords in English, Chinese, Russian, Spanish, Portuguese, Japanese and Korean) and checks each one against
**live GitHub state**. It flags the phantoms. It then ranks whatever survives by **expected dollars per hour of work**,
and writes down why each factor got its value.

It is read-only: it sends only `GET` requests and never comments, forks or opens PRs.

## Why: what we measured (scan of 2026-10-02)

We ran a deeper prototype of this pipeline (Algora + Opire listings checked against live GitHub and the
platforms' own public APIs) on **2026-10-02**:

- **Algora:** GitHub search for open issues commented on by `algora-pbc` returned **371** listed bounties.
  - **174** were left after removing spam/bait orgs.
  - **81** still had a live, non-cancelled, non-awarded bounty marker of at least $20.
  - **31** were also open, unlocked, unassigned and in a repo with recent commits.
  - **9** were confirmed live by Algora's own data.
  - **1** was fresh.
  - **0** were uncontested.
- **38** issues were **still open after the bot announced the bounty had been awarded**.
- **Opire:** the platform API listed **6 available rewards totalling $212**. Over its whole history it has paid
  **44 bounties / $4,975.87**. GitHub, meanwhile, shows **113 "ghost" issues** with Opire reward traffic but no
  available reward in Opire's API.

This tool's own v0.1 runs on the same day (live and read-only; see [`reports/`](reports/); per-org hygiene audits are kept private):

- **`ghostbuster scan`** looked at the 40 most recently updated of 391 open Algora-commented issues.
  **5** were phantoms, **35** were risky and **0** were live. **39 of 40** were swarmed (5 or more distinct `/attempt` or `/claim` users).
- **`ghostbuster hygiene`** audited 10 funding orgs and **78** open bounty issues. **29** were phantoms: 13 had been awarded
  but were still open, and 15 were in archived repos. **114 open PRs** pointed at those phantoms, roughly **456 contributor-hours**
  if each PR took 4h (an assumption).

So of 371 listed Algora bounties, **zero** were fresh, payable and not already swarmed. Every one of them would have
cost a contributor time. Most of that time goes on checks this tool runs for you in seconds.

## What it checks (v0.1)

| Flag | Verdict | Meaning |
|---|---|---|
| `repo_gone` | 👻 PHANTOM | repo returns 404 (deleted, private or renamed away) |
| `issue_deleted` | 👻 PHANTOM | issue returns 404/410 |
| `issue_closed` | 👻 PHANTOM | closed (`completed` / `not_planned`) |
| `is_pull_request` | 👻 PHANTOM | the listing points at a PR |
| `repo_archived` | 👻 PHANTOM | archived repo: nothing can be merged |
| `already_paid` | 👻 PHANTOM | `🎉🎈 … has been awarded` / Opire "completed the payment" / `rewarded`/`paid` label, but the issue is still open |
| `cancelled_struck` | 👻 PHANTOM | `~~💎 $X bounty~~`: the amount is struck through (cancelled) |
| `merged_fix` | 👻 PHANTOM | a **same-repo** PR referencing the issue is already merged (merged PRs in other repos are ignored) |
| `no_bounty_marker` | 👻 PHANTOM | no bot comment, label or keyword+amount |
| `swarmed` | ⚠️ RISKY | 5 or more distinct users posted `/attempt` or `/claim` |
| `competing_prs` | ⚠️ RISKY | 2 or more open same-repo PRs, with CI state (green/fail/pending) of the newest ones |
| `ai_banned` | ⚠️ RISKY | CONTRIBUTING / AI_POLICY bans AI-generated or AI-assisted PRs |
| `repo_redirected`, `issue_locked`, `assigned`, `stale_repo`, `stale_bounty` | ⚠️ RISKY | self-explanatory |

### EV/h scoring

```
EV/h = B × P_V × P_A × P_C × P_P / T
```

- **B** – bounty amount (bot comment first, then issue text)
- **P_V** – the bounty is valid (platform bot vs. self-declared)
- **P_A** – a maintainer will accept a PR (lower for stale repos, old bounties, AI bans, locked or assigned issues)
- **P_C** – you win the competition: `1/(1 + open PRs + 0.15 × claimants)`
- **P_P** – you actually get paid (Algora vs. Opire vs. self-declared)
- **T** – hours to a defensible PR (S = 4h, M = 10h, L = 24h, estimated from the issue text)

Every factor in the report comes with a one-line justification. The scores are heuristics, not promises.

## Install & use

```bash
pip install git+https://github.com/albertotranquilli-cmyk/bounty-ghostbuster
export GITHUB_TOKEN=$(gh auth token)       # or any read-only token; falls back to `gh auth token`

ghostbuster scan --issue trpc/trpc#4306 --issue lablab-ai/community-content#462
ghostbuster scan --query "commenter:app/algora-pbc is:issue is:open" --limit 40 -o report.md --json-output report.json
ghostbuster scan --query 'label:"💎 Bounty" is:open' --format json
ghostbuster scan --query '赏金 is:issue is:open' --limit 20         # multilingual discovery
ghostbuster hygiene --org tscircuit -o hygiene-tscircuit.md       # bounty hygiene audit for a funding org
```

See [`reports/sample-report.md`](reports/sample-report.md) for a real run.

### Single-issue gate (for bots, watchers and daemons)

```bash
ghostbuster gate trpc/trpc#4306 --json      # exit code 2 = PHANTOM, 0 = RISKY/LIVE
```

```python
import ghostbuster
d = ghostbuster.gate("trpc/trpc", 4306)
# {'verdict': 'PHANTOM', 'go': False, 'reasons': {'cancelled_struck': '...'}, 'amount_usd': 50.0,
#  'P': {...} | None, 'EV_h': ... | None, 'why': {...}, 'open_prs': 0, 'claimants': 0, ...}
```

`go` is `True` only when the verdict is LIVE and EV/h ≥ 3.0.

## Bounty hygiene mode (for orgs that fund bounties)

`ghostbuster hygiene --org X` audits an org's own open bounty issues. It reports:

- issues already awarded or paid but still open (or still carrying a bounty label)
- amounts that differ between the bot comment and the issue title, label or text
- bounties older than 12 months, with how many people have swarmed each one
- locked issues that still advertise a live bounty
- an **estimate of contributor hours wasted** on phantom bounties (open PRs on phantom bounties × hours per attempt)

Open PRs pointed at a ghost bounty are unpaid work. Orgs that fund bounties have every reason to clean these up,
and hunters have every reason to avoid them.

Per-org hygiene audits are available on request (they are not published, to avoid naming individual projects).

## GitHub Action

```yaml
# .github/workflows/ghostbuster.yml in your own repo
on:
  schedule: [{cron: "0 6 * * *"}]
  workflow_dispatch:
permissions: {contents: read, issues: write}
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: albertotranquilli-cmyk/bounty-ghostbuster@v0.1
        with:
          query: "commenter:app/algora-pbc is:issue is:open"
          limit: "40"
          issue-title: "👻 Daily bounty ghost report"   # optional: create/update an issue in THIS repo
```

The report always goes to the job summary. The action only writes anything when `issue-title` is set, and then
it writes a single issue in the repository that runs it.

## Free vs. Pro (planned)

| | Free (MIT, this repo) | Pro (sponsors) |
|---|---|---|
| Phantom checks above, CLI + Action, hygiene mode | ✅ | ✅ |
| Markdown/JSON report, EV/h with justifications | ✅ | ✅ |
| Multilingual discovery (EN/ZH/RU/ES/PT/JA/KO query packs, deduped across platforms) | keyword detection only | ✅ curated query packs |
| Platform cross-checks (Algora public org totals, Opire public API status, payer history) | — | ✅ |
| Ranked EV/h feed + diff since last run | — | ✅ |
| Alerts (issue/email/webhook) when a fresh, uncontested bounty appears | — | ✅ |

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]" && .venv/bin/pytest -q
ghostbuster scan --issue o/r#1 --record tests/fixtures/rec   # record new fixtures (status + JSON body only, no headers/tokens)
```

## Limits & honesty

- Heuristics: an amount parsed from free text, or a "stale" judgement, can be wrong. Always read the issue.
- v0.1 does not query Algora's or Opire's own APIs (that is a planned Pro feature), so a bounty that looks
  live on GitHub but is cancelled on the platform can still show as LIVE/RISKY.
- GitHub search caps results at 1,000 per query, and scans use your token's rate limit (about 6–10 calls per issue).

MIT © 2026 Alberto Tranquilli
