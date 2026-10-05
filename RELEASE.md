# Releasing bounty-ghostbuster

Tags are created from the CLI (the GitHub connector cannot push tags).

```bash
git checkout main && git pull
git tag -a v0.1.0 -m "v0.1.0: phantom-bounty scanner + GitHub Action"
git push origin v0.1.0
```

Then create the release on GitHub (or `gh release create v0.1.0 --title "v0.1.0" --notes-file RELEASE.md`), and the Action reference `albertotranquilli-cmyk/bounty-ghostbuster@v0.1` in the README resolves.

## What v0.1 contains

- `ghostbuster` CLI: `scan`, `gate`, `hygiene` (read-only, GET only)
- GitHub Action (composite) with optional report-issue publishing
- EV/h scoring with per-factor justifications
- Multilingual discovery keywords (EN/ZH/RU/ES/PT/JA/KO)
- pytest suite with recorded fixtures
- CI workflow: `.github/workflows/ci.yml`
