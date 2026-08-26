# Local Development

How to run the full OVOS Localize pipeline locally without deploying to GitHub.

## Prerequisites

```bash
uv pip install -e ".[dev]"
```

Zero external dependencies — everything uses Python stdlib.

## 1. Generate Data

```bash
python scripts/generate_data.py
```

This clones every repo in `skills.txt` into `repos/` (shallow clone), scans locale directories, runs AST analysis and validation, then writes JSON to `data/`.

First run takes several minutes (cloning ~60 repos). Subsequent runs are faster (git pull only).

### Subset testing

To test with fewer skills, create a temporary `skills.txt`:

```bash
# Back up the full list
cp skills.txt skills.txt.bak

# Test with just 2 skills
cat > skills.txt << 'EOF'
OpenVoiceOS/ovos-skill-hello-world
OpenVoiceOS/ovos-skill-weather
EOF

python scripts/generate_data.py

# Restore
mv skills.txt.bak skills.txt
```

### Output structure

After running, `data/` contains:

```
data/
├── repos.json              # Skill index (all skills)
├── coverage.json           # Language × skill coverage matrix
├── validation.json         # Aggregated validation results
└── skills/
    ├── ovos-skill-hello-world.json
    ├── ovos-skill-weather.json
    └── ...
```

## 2. Serve the SPA

```bash
python -m http.server 8000
```

Open [http://localhost:8000](http://localhost:8000) in a browser.

### Views

| URL | What you see |
|-----|-------------|
| `http://localhost:8000/#/` | Dashboard — coverage heatmap, 53 skills × 40 languages |
| `http://localhost:8000/#/skill/ovos-skill-weather` | Skill detail — file list with per-language validation badges |
| `http://localhost:8000/#/skill/ovos-skill-weather/weather.intent/de-de` | Translation editor — source panel, editable textarea, context card |

### Submitting translations

The editor view has a **"Submit as PR"** button. The workflow:

1. Click **Sign in** in the header
2. Paste a [GitHub Personal Access Token](https://github.com/settings/tokens/new?scopes=public_repo&description=OVOS+Translate) with `public_repo` scope
3. Navigate to a file and language (e.g. `#/skill/ovos-skill-weather/weather.intent/de-de`)
4. Edit the translation in the center textarea
5. Click **Submit as PR**

What happens behind the scenes:
- Forks the skill repo to your GitHub account (idempotent)
- Creates a `translate/{lang}/{file}` branch on your fork
- Commits the edited file
- Opens a PR from your fork to the upstream `dev` branch
- Opens the PR in a new tab

The token is stored in `localStorage` only — never sent anywhere except the GitHub API.

### Troubleshooting

**Dashboard shows nothing / fetch errors in console:**
- Verify `data/repos.json` exists and is valid JSON: `python -m json.tool data/repos.json > /dev/null`
- The server must run from the repo root (where `index.html` and `data/` both live)

**"Submit as PR" fails with 404:**
- Your token may lack `public_repo` scope — regenerate it
- The fork may not be ready yet — wait a few seconds and retry

**"Edit on GitHub" links point to wrong branch:**
- Links follow the branch the scan resolved for that repo, recorded as `branch`
  in `data/repos.json`. Regenerate the data if a repo changed its default branch.
- `dev` is used only as a last resort, when no branch was resolved.

## 3. Validate a Single Skill

No data generation needed — the CLI works standalone:

```bash
# Text output
ovos-localize-cli --repo /path/to/ovos-skill-weather

# GitHub Actions annotation format (for CI)
ovos-localize-cli --repo /path/to/ovos-skill-weather --report-format github

# JSON output
ovos-localize-cli --repo /path/to/ovos-skill-weather --report-format json
```

Exit code: `0` = no errors, `1` = validation errors found.

## 4. Run Tests

```bash
uv run pytest test/ -v
```

With coverage:

```bash
uv run pytest test/ -v --cov=ovos_localize --cov-report=term-missing
```

## 5. Scan a Single Repo Programmatically

```python
from ovos_localize.sync.github import RepoScanner
from ovos_localize.analyzers.context_builder import build_context_card

scanner = RepoScanner("./repos")
scan = scanner.full_sync("OpenVoiceOS", "ovos-skill-weather")

print(f"Skill: {scan.skill_class_name}")
print(f"Languages: {scan.languages}")
print(f"Files: {len(scan.locale_files)}")

for f in scan.locale_files:
    if f.lang == "en-us":
        card = build_context_card(f, scan.skill_analysis, scan.locale_files)
        print(f"\n{f.base_name}.{f.file_type.value}: {card.file_type_label}")
        if card.handler_method:
            print(f"  Handler: {card.handler_method}() at :{card.handler_line}")
        if card.tips:
            print(f"  Tips: {card.tips[0]}")
```

## Accessibility (WCAG 2.2)

The SPA ships with the structural accessibility baseline:

- a skip-to-content link (visually hidden until focused) targeting `<main id="app">`;
- semantic landmarks (`header` / `nav[aria-label="Primary"]` / `main` / `footer`);
- **focus management on hash-route change** — after each view renders, focus moves
  to its heading (or `<main>`) so screen-reader users are told the page changed;
- a polite live region (`#toast-container`) so toast/status messages are announced;
- visible keyboard focus rings (`:focus-visible`) on all interactive elements.

Not yet automated (follow-ups): an `axe-core` CI gate, a per-view
single-`h1` audit, and a colour-contrast pass on the dark
theme. Run a manual keyboard-only + screen-reader pass on the editor before
release — automated tooling catches only ~30–40% of real issues.
## End-to-end (SPA) tests

Playwright smoke tests for the single-file SPA live in `e2e/` (kept out of the
unit `test/` directory so they never gate the fast unit suite). They serve the
repo over HTTP and drive a headless browser; the SPA tolerates missing data, so
no fixtures are needed.

```bash
pip install -e ".[e2e]"
python -m playwright install chromium
pytest e2e/
```

CI runs them in a dedicated `E2E` workflow that installs the browser. This is
the harness that makes further SPA changes (RTL, accessibility, batch editing)
safe to evolve.
