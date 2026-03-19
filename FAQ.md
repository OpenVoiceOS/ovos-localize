# FAQ - ovos-localize

### What is ovos-localize?
`ovos-localize` is a GitHub-native translation platform designed specifically for OpenVoiceOS locale files. It uses contextual cues from skill source code to provide better translation quality.

### How do I run the validator locally?
You can use the CLI tool:
```bash
ovos-localize-cli validate /path/to/skill-repo
```

### Why does it need `language_data`?
The `langcodes` library uses `language_data` to provide human-readable display names for language codes (e.g., "en-US" → "English (United States)").

### How do I run tests?
Ensure you have the `dev` dependencies installed:
```bash
uv sync --extra dev
uv run pytest
```

### Are there open datasets available for Machine Learning?
Yes! `ovos-localize` automatically processes all OpenVoiceOS language files and generates machine-learning datasets in JSONL format. You can find them under the `data/datasets/` directory. These include Intent Classification datasets (for NLU) and Parallel Corpora (for machine translation), all of which update daily via GitHub Actions.

### Why were eu-EU, eu, and es-LM dataset files removed?
After BCP-47 normalization was added (`lang_utils.EXPLICIT_MAPPING`), `eu-EU` and `eu` both normalize to `eu-ES`, and `es-LM` normalizes to `es-419`. The old files contained data tagged with deprecated codes; they were replaced by `eu-ES.jsonl` and `es-419.jsonl`.
