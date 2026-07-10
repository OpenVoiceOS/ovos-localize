# OVOS Localize: A GitHub-Native Translation Platform for Voice Assistant Locale Files

**OpenVoiceOS Project — Technical Whitepaper**
*March 2026*

---

## Abstract

Localising a voice assistant is qualitatively different from localising a web application. Where web i18n deals with display strings, voice assistants require training data: intent examples that cover a wide range of phrasings, keyword vocabularies for pattern matching, text-to-speech dialogue variants for natural-sounding responses, and slot-filling entity sets. Generic translation platforms treat all of these as interchangeable key-value pairs, producing translations that are technically present but linguistically wrong.

OVOS Localize is a purpose-built translation platform for OpenVoiceOS skill locale files. It provides type-aware editors backed by Python source code analysis, a fully automated pull-request pipeline that requires only a GitHub account, a validation engine with 15+ rules tuned to OVOS file semantics, and a daily-refreshed open ML dataset derived from community contributions. The entire platform runs on GitHub Pages and GitHub Actions — zero servers, zero databases, zero vendor lock-in.

---

## 1. Introduction

### 1.1 The Localisation Gap in Voice Assistants

Voice assistant platforms depend on locale files in ways that differ fundamentally from GUI applications. An `.intent` file is not a label; it is a training set for a probabilistic intent classifier. A `.dialog` file is not a tooltip; it is a corpus of TTS utterances where variety prevents robotic repetition. A `.voc` file is not a menu item; it is a set of keywords whose presence in a spoken utterance determines whether an intent fires.

These distinctions matter for translation quality. A translator who sees a line like:

```
turn {brightness} the {light_name}
```

without context does not know that `{brightness}` is a slot that expects values like *up*, *down*, *brighter*, or *dimmer*, and that 10 or more phrasings are needed to train a reliable classifier. Without that knowledge, the translator produces a single grammatically correct sentence that fails in production.

### 1.2 Prior Art and Its Limitations

OpenVoiceOS previously used GitLocalize for community translations. GitLocalize is a capable general-purpose tool, but it was ill-suited to OVOS for three reasons:

1. **Blind translation.** GitLocalize presents files line by line with no knowledge of what each line means in context. Translators cannot see which Python handler uses a dialog file, what slots an intent expects, or how many variants are required.

2. **No type awareness.** All OVOS file types look like plain text to GitLocalize. There is no validation that an `.intent` file has sufficient training diversity, or that a `.dialog` file preserves `{variable}` substitutions.

3. **Third-party dependency.** GitLocalize is a hosted service. Outages, pricing changes, or discontinuation would halt all OVOS translation work. Community data lives on an external platform rather than in the skill repositories themselves.

### 1.3 Goals

OVOS Localize was designed to address these gaps while adding two capabilities that GitLocalize never offered: CI integration and open ML dataset generation.

---

## 2. Design Goals

| Goal | Rationale |
|------|-----------|
| **Zero infrastructure cost** | The platform must be sustainable indefinitely on a volunteer budget. No servers, no databases. |
| **No account required beyond GitHub** | Lowering the barrier to contribution is critical for community-driven projects. Every developer already has a GitHub account. |
| **Type-aware editing and validation** | Each of the 8 OVOS locale file types has different structural requirements. The editor and validator must understand them. |
| **AST-powered context** | Translators need to see the Python handler that uses each file, the slots that appear in it, and the intents connected to it — without leaving the editor. |
| **ML-ready output** | Translations should automatically generate structured datasets useful for training TTS models, intent classifiers, and translation models. |
| **Self-healing automation** | Mechanical issues (bare language codes, missing locale directories) should be auto-fixable via workflow, not require manual maintainer intervention. |
| **Auditable by design** | All translations flow through PRs with full git history. Every contribution is attributable. |

---

## 3. Architecture

### 3.1 The GitHub-Native Stack

The central architectural decision was to treat GitHub as the entire platform:

| Traditional role | GitHub equivalent |
|-----------------|-------------------|
| Web server / CDN | GitHub Pages (serves `index.html` + `data/`) |
| Database | Git-tracked JSON files in `data/` |
| Authentication | GitHub App tokens (scoped, ephemeral) |
| Background jobs | GitHub Actions (scheduled + event-triggered) |
| Form submission API | GitHub Issues (machine-readable body) |
| CI/CD | GitHub Actions (shared reusable workflows) |
| Bot identity | GitHub App (`ovos-localize[bot]`) |

This means the platform has no moving parts outside of GitHub's own infrastructure, which has a 99.9% uptime SLA and is already trusted by every contributor.

### 3.2 Data Pipeline

```
skills.txt
    ↓
generate_data.py (daily via GitHub Actions)
    ├── clone_or_pull() — shallow clone, branch fallback (dev → main → master)
    ├── scan_locale_directory() — discovers locale dirs, flags bare lang codes
    ├── Per-file parsers (IntentParser, VocabParser, DialogParser, …)
    ├── AST analysis (ast_analyzer.py) — extracts handler→file connections
    ├── Validation (validators/rules.py) — 15+ rules, error/warning/info
    └── Dataset builders (classification, translation, slot_filling, …)
    ↓
data/
    ├── repos.json         — skill index with metadata
    ├── coverage.json      — language × skill coverage matrix
    ├── validation.json    — aggregated validation results
    ├── stats.json         — metrics by language/file type
    ├── issues.json        — surfaced problems (bad lang codes + rule violations)
    ├── entities.json      — all entity files across skills
    ├── skills/{id}.json   — per-skill detail with entries, context cards, handler source
    └── datasets/          — JSONL ML datasets (split at 100 MB)
    ↓
GitHub Pages → index.html (SPA)
```

The pipeline runs daily at 02:00 UTC, on manual dispatch, and whenever `skills.txt` changes. Additionally, a lightweight polling workflow (`poll_merged_fixes.yml`) runs every 30 minutes and triggers a data refresh if any locale-fix or translation PRs were merged across the org since the last data commit — ensuring the UI reflects upstream fixes within 30 minutes instead of waiting for the next daily run. All output is committed back to the `dev` branch and served immediately via Pages.

### 3.3 Single-Page Application

The frontend is a single `index.html` file (~4,000 lines) using vanilla JavaScript and Tailwind CSS. No framework, no build step, no `node_modules`. This is a deliberate choice: the file can be audited in one pass, works offline after caching, and has no dependency rot.

Routes use hash navigation (`#/dashboard`, `#/skill/{id}`, `#/skill/{id}/{file}/{lang}`) so they work on GitHub Pages without server-side routing. Data is fetched lazily from the `data/` directory.

### 3.4 GitHub App Token Lifecycle

Each translation submission generates a fresh, scoped token:

1. A GitHub Issue is opened with a machine-readable `TRANSLATION_META` block in the body.
2. The `submit_translation` workflow triggers.
3. `actions/create-github-app-token` exchanges the App's private key for a short-lived installation token (valid 1 hour, scoped to the target skill repository only).
4. The workflow uses this token to check out the skill repo, create a branch, commit the translation, and open a PR.
5. The token expires. No credential is persisted.

This model means the platform never stores user credentials. The GitHub App is a first-class auditable entity with granular permissions (`contents: write`, `pull-requests: write` on target repos only).

---

## 4. File Type System

OVOS locale files are not interchangeable. OVOS Localize gives each type its own parser, validator, and editor presentation:

| File type | Purpose | Key constraints |
|-----------|---------|-----------------|
| `.intent` | Padatious training utterances | ≥10 expanded sentences, slot preservation, lexical diversity ≥0.25 |
| `.voc` | Adapt keyword lists | Non-empty, warn if >5 words per line, no newlines |
| `.dialog` | TTS response variants | ≥2 variants, `{variable}` preservation, balanced bracket syntax |
| `.entity` | Slot-filling examples | ≥5 examples, valid entries |
| `.rx` | Regex extraction patterns | Compiles without error, named groups match source slots |
| `skill.json` | Skill metadata | Valid JSON, required keys present |
| `settingsmeta.*` | Settings UI definition | Structure preserved, no breaking schema changes |
| `resource_json` | Generic JSON resources | Valid JSON, key structure preserved |

This taxonomy is baked into the data model (`ovos_localize/enums.py:FileType`) and propagates through parsers, validators, and the frontend editor. When a translator opens a `.intent` file, they see a diversity score, a slot legend, and a minimum-line warning. When they open a `.dialog` file, they see a variant counter and a substitution preview.

### 4.1 Bracket Expansion

Padatious supports template syntax: `(wake up|get up) {name} [please]`. The number of training sentences is the product of alternatives, not the number of lines. OVOS Localize implements bracket expansion (`ovos_localize/bracket_expansion.py`) to correctly count expanded sentences before applying diversity and minimum-count rules, preventing false positives on compact templates.

---

## 5. AST-Powered Context

### 5.1 The Blind Translation Problem

Consider a translator working on `locale/de-DE/query_weather.dialog`. The file contains:

```
It is {temp} degrees {condition} in {location}
```

Without context, the translator cannot answer: What triggers this dialog? What are the possible values of `{condition}`? Is this a confirmation or an announcement? Is `{location}` always populated?

GitLocalize offers no help here. The translator produces a grammatically plausible German sentence that may be structurally incorrect (wrong case, wrong word order around substitutions) and will sound robotic in production.

### 5.2 Python AST Analysis

`ovos_localize/analyzers/ast_analyzer.py` walks the skill's Python source at data generation time, extracting:

- `@intent_handler` decorators referencing `.intent` or `.voc` files → which handler consumes each intent
- `self.speak_dialog("query_weather")` calls → which handler produces each dialog file
- `self.get_response()` and `self.ask_yesno()` calls → interactive dialog usage
- Handler method source code (first ~15 lines) for display in the context card

This information is stored in each skill's `data/skills/{id}.json` and surfaced in the three-panel editor as a "context card" on the right side: handler name, method source, connected intents, and slot definitions.

The result is that a translator sees not just the string to translate, but the exact Python method that will speak it, the user utterance that triggered the intent, and the slots they need to preserve.

---

## 6. Automated Workflows

### 6.1 Issue-as-API-Call

All automation in OVOS Localize uses a pattern we call *issue-as-API-call*: structured data is embedded in a GitHub Issue body as an HTML comment block, which is invisible to human readers but machine-readable by workflows. Example:

```html
<!-- TRANSLATION_META
skill: OpenVoiceOS/ovos-skill-weather
file: weather.intent
lang: de-DE
-->
<content>
Wie wird das Wetter in {location}
Wettervorhersage für {location}
...
</content>
```

The SPA generates this block automatically when the user clicks "Submit as PR". The user only sees the issue form; they never write the metadata block manually.

### 6.2 Six Workflows

| Workflow | Trigger | Action |
|----------|---------|--------|
| `update_data` | Daily 02:00 UTC; manual; `skills.txt` push | Run data pipeline, commit results to `dev` |
| `poll_merged_fixes` | Every 30 min (cron) | Search for recently merged locale-fix/translation PRs; trigger `update_data` if any found since last data commit |
| `submit_translation` | Issue opened with `translation` label or `[translate]` title | Create branch, commit translation, open PR on skill repo |
| `enable_new_language` | Issue opened with `new-language` label | Open PR adding BCP-47 code to `config/enabled_languages.txt` |
| `fix_lang_code` | Issue opened with `fix-lang-code` label | Rename locale directories from bare code to BCP-47 form, open PR |
| `add_skill` | Issue opened with `add-skill` label | Add skill to `skills.txt`, open PR |

### 6.3 Auto-Fix for Mechanical Issues

The `fix_lang_code` workflow handles a class of problems that are safe to automate: locale directory names that use bare ISO 639-1 codes (`eu`, `da`, `ca`) instead of full BCP-47 codes with region subtags (`eu-ES`, `da-DK`, `ca-ES`). These are unambiguous because the OVOS community uses a canonical mapping (e.g., Basque is always `eu-ES`; Danish is always `da-DK`).

The workflow parses a `FIX_LANG_CODE_META` block from the issue body, checks out the target skill repo using a scoped GitHub App token, runs a Python snippet to rename the directories, and opens a PR. The skill maintainer reviews and merges — no manual file editing required.

Issues with translation *content* (diversity, variable preservation, sentence count) are surfaced in the Issues view with a "Report" button that opens a pre-filled issue in the skill repository with per-file, per-line detail. These require human judgment and are handled by maintainers.

### 6.4 Reactive Data Refresh via Polling

A known limitation of the daily data pipeline is staleness: when a `fix_lang_code` PR is merged on a target repo, the Issues view continues to show the problem until the next pipeline run. Since the fix PRs live on external repos (not on ovos-localize itself), GitHub's built-in event triggers cannot detect the merge.

The `poll_merged_fixes` workflow addresses this by running every 30 minutes. It compares the timestamp of the last `chore: update translation data` commit against GitHub's search API for recently merged PRs matching the bot's title patterns (`"fix: rename bare lang code"` and `"OVOS Localize"`). If any merges occurred since the last data commit, it triggers the full `update_data` pipeline via `workflow_dispatch`. This keeps the polling step lightweight (two API calls, no checkout beyond the git log) while ensuring the UI reflects upstream fixes within 30 minutes.

### 6.5 Skill Submission

The `add_skill` workflow allows community members to add new skill repositories to the tracked list via a GitHub Issue. The issue body contains an `ADD_SKILL_META` block with the repository URL. The workflow parses the URL, verifies the repository exists, appends it to `skills.txt`, and opens a PR. The UI pre-checks for duplicate submissions by querying open issues before allowing a new submission.

---

## 7. Validation Engine

### 7.1 Rules by File Type

The validation engine runs at data generation time and emits structured `ValidationIssue` objects with a `rule_name`, `severity`, `file_path`, `line_number`, and `message`.

**`.intent` rules**: `intent.min_sentences` (≥10 expanded), `intent.slot_preservation` (source slots present in translation), `intent.regex_validity`, `intent.diversity_score` (Jaccard ≥0.25), `intent.no_pipe_in_alt` (flags `(word)` without pipe — likely missing alternative), `intent.unbalanced_parens`.

**`.voc` rules**: `vocab.non_empty`, `vocab.long_entry_warning` (>5 words).

**`.dialog` rules**: `dialog.min_variants` (≥2), `dialog.variable_preservation`, `dialog.bracket_syntax`.

**`.entity` rules**: `entity.min_examples` (≥5), `entity.valid_entries`.

**`.rx` rules**: `regex.compiles`, `regex.named_group_match`.

**`skill.json` rules**: `skill_json.valid_json`, `skill_json.required_keys`.

### 7.2 CI Integration

Skills can opt in to PR-time validation via a shared reusable workflow from `OpenVoiceOS/gh-automations`:

```yaml
uses: OpenVoiceOS/gh-automations/.github/workflows/validate-translations.yml@dev
```

The CLI tool (`ovos-localize validate`) supports three output formats: `text` (human-readable), `github` (inline PR annotations), and `json` (machine-readable). When run in CI with `--format github`, it emits `::error` and `::warning` annotations that appear directly on the diff.

### 7.3 Issues View

The Issues view in the SPA surfaces two categories of problems:

- **Translation Quality** (community tab): rule violations by skill and language, with severity badge, affected files, and a "Report" button that generates a detailed issue body with a markdown table of affected lines.
- **Developer Issues** (maintainer tab): bare lang code warnings by repo, with a "Request Auto-Fix" button that triggers the `fix_lang_code` workflow.

Current state: 263 total issues across 57 skills — 109 `bad_lang_code` warnings and 154 validation rule violations across 16 rule types.

---

## 8. Open Data Pipeline

Every translation contributed through OVOS Localize becomes part of a publicly available ML dataset. The `ovos_localize/datasets/` package generates six dataset formats during each data pipeline run:

| Format | Content | Use case |
|--------|---------|----------|
| `classification/{lang}.jsonl` | Intent utterances with (skill, intent) label | Intent classifier training |
| `translation/{lang_pair}.jsonl` | English ↔ target language parallel pairs | Translation model fine-tuning |
| `slot_filling/{lang}.jsonl` | Intent templates + slot names + entity values | NER / slot-filling training |
| `response_pairs/{lang}.jsonl` | (utterance, response) pairs via AST handler analysis | Dialogue model training |
| `tts/{lang}.jsonl` | Deduplicated dialog sentences | TTS corpus |
| `skill_metadata/{lang}.jsonl` | Multilingual skill name, description, examples | Skill discovery / search |

Datasets are written as JSONL files to `data/datasets/`, split at 100 MB for GitHub compatibility, and compatible with HuggingFace Datasets via direct URL reference.

---

## 9. Results

As of March 2026:

| Metric | Value |
|--------|-------|
| Skills indexed | 57 |
| Languages supported | 30 |
| Source locale files | 2,252 |
| File types handled | 8 |
| Validation rules | 15+ |
| Issues surfaced | 263 |
| ML dataset formats | 6 |
| Data refresh cadence | Daily + reactive (≤30 min after merged fixes) |
| Infrastructure cost | $0/month |

Languages span European, Slavic, Middle Eastern, and Baltic families including both Portuguese variants (`pt-BR`, `pt-PT`), both Spanish variants (`es-ES`, `es-419`), both Swedish variants (`sv-SE`, `sv-FI`), and both Dutch variants (`nl-NL`, `nl-BE`).

---

## 10. Lessons Learned

### 10.1 URL as API Has Limits

Early versions of the "Report" button encoded the full findings table into the GitHub issue creation URL. GitHub rejects URLs longer than approximately 8,000 characters with a generic "Whoa there!" error. The solution was to sort findings (line-number rows first, then by file path), greedily add rows until the encoded URL would exceed 7,500 characters, then append a truncation note with the count of omitted rows and a link back to the Issues view for the full list.

### 10.2 BCP-47 Is Not Universally Followed

Of 57 skills scanned, 109 bare language code directories were found — locale directories named `eu`, `da`, `ca` rather than `eu-ES`, `da-DK`, `ca-ES`. These are unambiguous in the OVOS community context but cause problems for tools that expect full BCP-47 codes. The `EXPLICIT_MAPPING` dictionary in `lang_utils.py` handles 15+ normalizations; the `fix_lang_code` workflow automates the rename.

Some codes are context-dependent: `pt` normalises to `pt-BR` (the dominant OVOS Portuguese locale), but `pt-PT` is preserved as distinct. `es-LM` (a non-standard Latin American code used in some older skill repos) normalises to `es-419` (the correct BCP-47 form). `fa-FA` normalises to `fa-IR`.

### 10.3 Branch Naming Is Not Standardised

The OVOS ecosystem has no enforced branch naming convention. Among 57 skills: most use `dev`, some (particularly OscillateLabsLLC repos) use `main`, and a few legacy repos use `master`. The `clone_or_pull()` function in `sync/github.py` implements a fallback chain: preferred branch → `dev` → `main` → `master`, raising `RuntimeError` only if none exist. This was discovered when three OscillateLabsLLC skills were silently skipped during early data pipeline runs.

### 10.4 AST Analysis Has Edge Cases

Python AST analysis covers the common patterns in OVOS skills: `@intent_handler` with string literals, `self.speak_dialog("name")` with string literals. Skills that use computed dialog names (`self.speak_dialog(f"weather_{condition}")`) or dynamically registered intents do not expose their connections to the AST analyzer. These files receive no context card, but are still parsed and validated correctly.

---

## 11. Future Work

- **Machine translation suggestions.** Integrate a translation memory or MT API to pre-populate translation fields with suggestions, reducing cold-start friction for low-coverage languages.
- **Expanded skill coverage.** Add skill repositories from community contributors beyond the current OpenVoiceOS and OscillateLabsLLC orgs via a reviewed `skills.txt` contribution process.
- **OVOS-specific model fine-tuning.** Use the generated datasets to fine-tune intent classifier and TTS models specifically for the OVOS voice profile.
- **Real-time collaboration.** Allow multiple translators to see each other's in-progress work on the same file, reducing duplication of effort.
- **Automated intent diversity checking.** Surface low-diversity intent files (score < 0.25) in the Issues view with targeted rewrite suggestions.

---

## References

- **langcodes** — BCP-47 language code parsing and normalization: https://github.com/rspeer/langcodes
- **Padatious** — Probabilistic intent parser (`.intent` file format): https://github.com/MycroftAI/padatious
- **Adapt** — Rule-based intent parser (`.voc` file format): https://github.com/MycroftAI/adapt
- **GitHub Apps documentation** — https://docs.github.com/en/apps
- **actions/create-github-app-token** — Short-lived installation token generation: https://github.com/actions/create-github-app-token
- **OpenVoiceOS** — https://github.com/OpenVoiceOS
- **OVOS Localize SPA** — https://openvoiceos.github.io/ovos-localize/
