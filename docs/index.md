# OVOS Localize

GitHub-native translation platform for OpenVoiceOS locale files with contextual cues extracted from skill source code.

## Problem

GitLocalize treats OVOS locale files as flat key-value pairs. Translators work blind — they don't know if a file is a Padatious training set (needs 10+ diverse examples) or an Adapt keyword list (needs short keywords). OVOS Localize makes every native file type a first-class citizen with context from skill code.

## Architecture

Fully GitHub-native: no server, no database, no Docker.

| Component | Tech | Purpose |
|-----------|------|---------|
| Data generation | `scripts/generate_data.py` | Clones skills, scans, outputs JSON to `data/` |
| Scheduling | GitHub Actions cron | Daily data refresh + auto-commit |
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
