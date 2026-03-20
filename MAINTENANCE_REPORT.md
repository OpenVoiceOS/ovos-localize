# Maintenance Report - ovos-localize

## [2026-03-19] - Fix Frontend Onboarding Guard
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
    - Extended public pages list to include `#/stats`, `#/entities`, `#/open-data` so they render without a saved profile.
    - Removed permanent accent styling on Open Data nav link (`index.html:96`).
    - Updated `FAQ.md`.
- **Oversight**: Verified via Chromium CDP — all three pages render without a profile.

## [2026-03-19] - Dataset Cleanup After BCP-47 Normalization
- **AI Model**: Claude Sonnet 4.6
- **Actions Taken**:
    - Deleted stale dataset files using deprecated lang codes (`eu-EU.jsonl`, `eu.jsonl`, `es-LM.jsonl` and translation counterparts).
    - Added regenerated datasets with normalized codes (`eu-ES.jsonl`, `es-419.jsonl`).
    - Staged and committed all modified skill JSON, coverage, stats, repos, entities, and TSV files.
    - Updated `FAQ.md` to explain the file removal.
- **Oversight**: 140 unit tests passing.

## [2026-03-19] - Dependency Fixes & Test Validation
- **AI Model**: Gemini 2.0 Flash
- **Actions Taken**:
    - Added `language_data>=1.1` to `pyproject.toml` to resolve `ModuleNotFoundError` in `langcodes` during name lookups.
    - Added `PyYAML` to `pyproject.toml` to support parsing of `settingsmeta.yml` files.
    - Synced local `.venv` using `uv`.
    - Verified all 139 unit tests pass with 90% coverage.
- **Oversight**: Automated verification via `pytest`.

## [2026-03-19] - Dataset Generator (Open Data)
- **AI Model**: Gemini 2.0 Flash
- **Actions Taken**:
    - Created `ovos_localize.datasets` package for generating ML datasets from parsed skills.
    - Implemented `classification.py` for NLU intent datasets.
    - Implemented `translation.py` for parallel corpora machine translation datasets.
    - Created pipeline script `scripts/generate_datasets.py` to auto-generate JSONL files.
    - Updated `.github/workflows/update_data.yml` to run the dataset generation in CI.
    - Updated `docs/index.md` to document the Open Data datasets.
- **Oversight**: Manual code review and local execution verified dataset generation success.

## [2026-03-19] - Dataset Refactoring & File Splitting
- **AI Model**: Gemini 2.0 Flash
- **Actions Taken**:
    - Refactored `generate_data.py` and `generate_datasets.py` to enforce a 48MB limit per file.
    - Implemented chunked JSON loading for per-skill detail files (e.g., `ovos-skill-days-in-history.json` split into 2 chunks).
    - Updated `index.html` with a new `fetchSkill` helper to seamlessly handle multi-chunk skill data.
    - Updated ML dataset generators to expand all sentence templates (`(a|b)`, `[optional]`) into unique utterances.
    - Implemented data cleaning for ML datasets: lowercase, remove extra whitespace, and deduplicate.
    - Refactored `dataset.tsv` to use expansion and splitting (now 100MB+ split into 3 files).
    - Removed JSON indentation across all generated data to optimize file size.
- **Oversight**: Verified file sizes are < 50MB and content is expanded/cleaned via local execution.
