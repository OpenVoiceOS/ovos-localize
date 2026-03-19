# Maintenance Report - ovos-localize

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
