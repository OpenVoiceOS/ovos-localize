# OVOS Localize

GitHub-native translation platform for OpenVoiceOS locale files with contextual cues extracted from skill source code.

## Problem

GitLocalize treats OVOS locale files as flat key-value pairs. Translators work blind — they don't know if a file is a Padatious training set (needs 10+ diverse examples) or an Adapt keyword list (needs short keywords). OVOS Localize makes every native file type a first-class citizen with context from skill code.

## Architecture

Fully GitHub-native: no server, no database, no Docker.

| Component | Tech | Purpose |
|-----------|------|---------|
| Data generation | `scripts/generate_data.py` | Clones skills, scans, outputs JSON to `data/` |
| Scheduling | GitHub Actions cron | Daily data refresh + auto-commit + polling for merged fixes |
| Frontend | `index.html` (static SPA) | Tailwind + vanilla JS, served via GitHub Pages |
| CLI | `ovos-localize-cli` | CI pipeline validation |

## Key Modules

| Module | Path | Description |
|--------|------|-------------|
| `parsers/` | `ovos_localize/parsers/` | Per-file-type parsers (.intent, .voc, .dialog, .entity, .rx, .value, skill.json, settingsmeta) |
| `analyzers/` | `ovos_localize/analyzers/` | AST analysis of skill Python source → `SkillAnalysis`, `ContextCard` |
| `validators/` | `ovos_localize/validators/` | Per-type validation rules (slot preservation, regex compilation, diversity scoring) |
| `sync/` | `ovos_localize/sync/` | Git clone/pull, locale directory scanning |
| `cli/` | `ovos_localize/cli/` | Standalone validation CLI for CI |
| `enums.py` | `ovos_localize/enums.py` | `FileType`, `IntentSystem` enums (pure stdlib) |

## Data Pipeline

1. `skills.txt` lists `org/repo` entries (one per line)
2. `scripts/generate_data.py` clones each repo, scans locale dirs, runs AST analysis + validation
3. Outputs to `data/`:
   - `repos.json` — skill index
   - `coverage.json` — language × skill coverage matrix
   - `validation.json` — aggregated validation results
   - `skills/{id}.json` — per-skill detail with entries, context cards, edit URLs

## Static SPA Views

| Route | View | Data Source |
|-------|------|-------------|
| `#/` | Dashboard + heatmap | `repos.json`, `coverage.json` |
| `#/skill/{id}` | Skill detail + file list | `skills/{id}.json` |
| `#/skill/{id}/{file}/{lang}` | Three-panel translation viewer | `skills/{id}.json` |
| `#/issues` | Locale issues + validation problems | `data/issues.json`, GitHub API |

## Supported File Types

| Extension | Type | Parser | Key Validations |
|-----------|------|--------|-----------------|
| `.intent` | Padatious training | `IntentParser` | Min 20 lines, slot preservation, diversity ≥0.25 |
| `.voc` | Adapt keywords | `VocabParser` | Non-empty, warn >5 words |
| `.dialog` | TTS response variants | `DialogParser` | Variable preservation, ≥2 variants |
| `.entity` | Slot examples | `EntityParser` | ≥5 examples |
| `.rx` | Regex extraction | `RegexParser` | Compiles, named groups match source |
| `.value` | Display→system CSV | `ValueParser` | Valid CSV, system values preserved |
| `skill.json` | Metadata | `SkillJsonParser` | Valid JSON, required keys |
| `settingsmeta.*` | Settings UI | `SettingsMetaParser` | Structure preserved |

## Quick Start

```bash
# Install (pure Python, zero dependencies)
uv pip install -e ".[dev]"

# Generate data (subset for quick test)
echo "OpenVoiceOS/ovos-skill-hello-world" > skills.txt
python scripts/generate_data.py

# Serve locally
python -m http.server 8000
# Open http://localhost:8000

# Validate a single skill
ovos-localize-cli --repo /path/to/skill --report-format github
```

See [local-development.md](local-development.md) for the full local workflow.

## Open Data (ML Datasets)

`ovos-localize` automatically generates machine-learning-ready JSONL datasets from the scanned skill data. These are hosted statically and updated daily.

Available datasets (`data/datasets/`):
- **Intent Classification** (`classification/{lang}.jsonl`): Maps `.intent` and `.voc` phrases to their respective skill domains and intent names. Ideal for training NLU or SLMs.
- **Parallel Corpora** (`translation/{lang_pair}.jsonl`): Pairs English (`en-US`) keys with corresponding translations (e.g., `pt-BR`) from `.dialog` and `.intent` files. Ideal for machine translation tasks.

You can load these directly via HuggingFace:
```python
from datasets import load_dataset
dataset = load_dataset("json", data_files="https://openvoiceos.github.io/ovos-localize/data/datasets/classification/en-US.jsonl")
```

`update_data.yml` also publishes `data/datasets/` to the
[`OpenVoiceOS/ovos-localize-intents`](https://huggingface.co/datasets/OpenVoiceOS/ovos-localize-intents)
dataset repo on every run, once the repository has an `HF_TOKEN` Actions
secret configured with write access to that dataset. Without the secret the
step is skipped and the Hub copy is left as it was last published.

## Data Refresh

Data refreshes automatically in three ways:
1. **Daily cron** — `update_data.yml` runs at 02:00 UTC
2. **On push** — when `skills.txt`, `scripts/`, or `ovos_localize/` change on `dev`
3. **Polling** — `poll_merged_fixes.yml` runs every 30 minutes, searches for recently merged locale-fix or translation PRs across the org, and triggers `update_data.yml` if any are found since the last data commit

## CI Integration

Skills can use the reusable workflow from `gh-automations`:

```yaml
# .github/workflows/validate-translations.yml
name: Validate Translations
on: [pull_request]
jobs:
  validate:
    uses: OpenVoiceOS/gh-automations/.github/workflows/validate-translations.yml@dev
```

## Cross-references

- `ovos-workshop` — `resource_files.py` for file type resolution, `skills/ovos.py` for intent registration
- `gh-automations` — Reusable CI workflows including `validate-translations.yml`
- `lang-support-tracker` — Sister project using same GitHub-native pattern (cron → JSON → SPA)
