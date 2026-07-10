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

### Why is a skill in skills.txt not being picked up?

The most common cause is a missing `dev` branch. The scanner defaults to cloning `dev`, and falls back to `main` then `master`. If none of those branches exist the clone will fail and the skill will be silently skipped. Check that the remote has at least one of those branches.

Also verify the skill has a `locale/` or `res/` directory with BCP-47 language subdirectories (e.g. `locale/en-us/`). Skills with no locale files are skipped even after a successful clone.

### How do I run tests?
Ensure you have the `dev` dependencies installed:
```bash
uv sync --extra dev
uv run pytest
```

### Are there open datasets available for Machine Learning?
Yes! `ovos-localize` generates six JSONL dataset families under `data/datasets/`, updated daily via GitHub Actions:

| Directory | Description | Key fields |
|---|---|---|
| `classification/` | Intent/voc utterances with skill+intent label | `lang`, `skill`, `intent`, `text` |
| `translation/` | Parallel corpora for machine translation | `pair`, `base_texts`, `target_texts` |
| `slot_filling/` | Intent templates with slot names + entity values | `template`, `slots`, `entity_values` |
| `response_pairs/` | (utterance, responses) pairs via AST handler analysis | `utterance`, `responses`, `handler` |
| `tts/` | Deduplicated dialog sentences for TTS training | `lang`, `dialog`, `text` |
| `skill_metadata/` | Multilingual skill name, description, examples, tags | `name`, `description`, `examples` |

### How are intent→dialog response pairs generated?
The `response_pairs` dataset is derived from AST analysis. At data-generation time, `context_builder.py` parses each skill's Python source and records `context.triggers_dialog` — the list of dialog file stems called by `self.speak_dialog()` in the intent handler. `generate_response_pairs()` uses this to pair intent utterances with their actual responses, without any string heuristics.

### Why do Stats, Entities, and Open Data work without setting up languages?
These are read-only informational pages. The onboarding (language selection) is only required for the Dashboard and skill editor pages, where user language preferences are used to filter content.

### Why does the entity create editor now work without setting up languages first?
The onboarding guard was blocking all `#/skill/...` routes for users without a saved profile. But skill editor URLs with an explicit lang in the route (e.g. `#/skill/foo/bar.entity/pt-PT`) don't need a profile — the language is already in the URL. The guard now allows these through.

### Why does clicking "+ create" on a gap entity work now?
Previously, `renderEditor()` crashed with `TypeError: Cannot read properties of undefined (reading 'type')` when opened in create mode (no existing file). The bug was `editor.dataset.fileType = fileData.type` — `fileData` is `undefined` in create mode. Fixed to use the already-computed `fileType` variable instead.

### What does the editor show in the source panel when creating a new entity file?
Instead of "No source file found", the source panel shows the `.intent` files that reference `{slotName}`, with their sample utterances. This gives context for what values belong in the entity file. The panel header also changes to "Used in intents".

### How do I add a brand-new language that has no translations yet?
Click **"Can't find your language? Request it"** in the language selection modal. Enter the language name and its BCP-47 code (e.g. `hi-IN`). This opens a GitHub issue with a machine-readable payload. A maintainer reviews the PR created by automation and merges it — after which the language appears in the UI at 0 % progress, ready for contributions.

The allowlist lives in `config/enabled_languages.txt` — `_load_enabled_languages()` in `scripts/generate_data.py` reads it and injects those codes into `coverage.json` even when no locale files exist yet. The data refresh is triggered automatically on PR merge.

### Who approves new language requests?
A maintainer must review and merge the automatically-created PR before the language appears. This prevents invalid codes (e.g. `klingon`, `xx-XX`) from polluting the platform.

### Why wasn't the automation triggered when I submitted a language request?
GitHub ignores `?labels=` query parameters for users without write access to the repo, so issues created via the frontend URL arrive without any labels. The `enable_new_language.yml` workflow now detects language requests by title prefix (`Add language:`) or body content (`NEW_LANGUAGE_META`) in addition to the `new-language` label, so label-less issues are handled correctly.

### How often does the data refresh?
Three ways: (1) daily cron at 02:00 UTC, (2) on push to `dev` when `skills.txt`/`scripts/`/`ovos_localize/` change, and (3) a polling workflow (`poll_merged_fixes.yml`) that runs every 30 minutes, checks if any locale-fix or translation PRs were merged across the org since the last data commit, and triggers a full refresh if so. This means the UI reflects upstream fixes within ~30 minutes instead of waiting for the next daily run.

### How do I add a new skill to the tracked list?
Click the "Submit a skill" button in the UI. Enter the GitHub repository URL. This opens a GitHub issue with a machine-readable `ADD_SKILL_META` block. The `add_skill` workflow parses the URL, appends it to `skills.txt`, and opens a PR. The UI checks for duplicate submissions before allowing a new one.

### Why were eu-EU, eu, and es-LM dataset files removed?
After BCP-47 normalization was added (`lang_utils.EXPLICIT_MAPPING`), `eu-EU` and `eu` both normalize to `eu-ES`, and `es-LM` normalizes to `es-419`. The old files contained data tagged with deprecated codes; they were replaced by `eu-ES.jsonl` and `es-419.jsonl`.
