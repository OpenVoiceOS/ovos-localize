# OVOS Localize

GitHub-native localization platform for [OpenVoiceOS](https://openvoiceos.org) skills. Replaces GitLocalize with a purpose-built tool that understands OVOS locale file types.

<img width="1075" height="947" alt="image" src="https://github.com/user-attachments/assets/fcc2b947-0d07-4775-b905-038b9d8236f9" />

## What it does

- **Scans** 50+ OVOS skill repos for locale files (.intent, .voc, .dialog, .entity, .rx, .value, skill.json)
- **Analyzes** skill Python source via AST to extract handler context (which function uses each file, what slots mean, what dialog it triggers)
- **Validates** translations with 15 rules (slot preservation, regex compilation, lexical diversity, variant count)
- **Serves** a static SPA on GitHub Pages where translators can browse, edit, preview, auto-translate, and submit translations as PRs
- **Exports** coverage stats and a unified intent dataset (TSV) for ML training

## For translators

Visit the live site, pick your languages, and start translating. The editor shows:

- English source on the left
- Editable translation in the center (with live bracket expansion preview)
- Skill code context on the right (the actual Python function that uses each file)

Translations are submitted as pull requests via a GitHub Action bot.

## Architecture

Fully GitHub-native. No server, no database, no Docker.

| Component | Purpose |
|-----------|---------|
| `scripts/generate_data.py` | Daily cron clones skills, scans, outputs JSON to `data/` |
| `index.html` | Static SPA (Tailwind + vanilla JS) served via GitHub Pages |
| `.github/workflows/update_data.yml` | Daily data refresh + auto-commit |
| `.github/workflows/submit_translation.yml` | Bot creates PRs from translator submissions |
| `ovos-localize-cli` | Standalone CLI for CI validation |

## Quick start

```bash
# Install
pip install ovos-localize

# Validate a skill's locale files
ovos-localize-cli --repo /path/to/skill --report-format text

# Generate data locally
pip install -e ".[dev]"
python scripts/generate_data.py
python -m http.server 8000
```

## Data outputs

| File | Contents |
|------|----------|
| `data/repos.json` | Skill index |
| `data/coverage.json` | Language x skill coverage matrix with display names |
| `data/stats.json` | Per-language, per-filetype aggregate metrics |
| `data/validation.json` | Aggregated validation results |
| `data/skills/{id}.json` | Per-skill detail (entries, context cards, handler source, edit URLs) |
| `data/dataset.tsv` | Unified intent/dialog/voc dataset for ML training |

## CI integration

Add to any skill repo:

```yaml
jobs:
  validate:
    uses: OpenVoiceOS/gh-automations/.github/workflows/validate-translations.yml@dev
```

## Documentation

- [docs/index.md](docs/index.md) — Architecture and module reference
- [docs/local-development.md](docs/local-development.md) — Local development guide
- [docs/deployment.md](docs/deployment.md) — GitHub Pages + Actions setup

## License

Apache 2.0 — see [LICENSE](LICENSE).

## Credits

Funded by [NGI0 Commons Fund](https://nlnet.nl/project/OpenVoiceOS) / [NLnet](https://nlnet.nl)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429),
through the European Commission's [Next Generation Internet](https://ngi.eu) programme.
