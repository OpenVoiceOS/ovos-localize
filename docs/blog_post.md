# We Built a Translation Platform That Runs Entirely on GitHub

*Posted to the OpenVoiceOS Blog — March 2026*

---

What if your translation platform had no servers? No accounts to create, no admin to email, no hosted service that could go down or change its pricing? What if the entire thing was just GitHub?

That's OVOS Localize — and after months of building it, we think it's the right way to do open-source localisation.

## The Problem With "Translation" for Voice Assistants

When most people think of translating an app, they imagine replacing display strings. `"Save"` becomes `"Speichern"`. `"Cancel"` becomes `"Annuler"`. It's mechanical, context is usually obvious, and any translation tool handles it fine.

Voice assistants are different.

Take this line from an OpenVoiceOS skill:

```
turn {brightness} the {light_name}
```

That's not a label. It's a training sentence for a probabilistic intent classifier. For the skill to recognise German users saying this, you need at least ten natural variations — and they all need to preserve `{brightness}` and `{light_name}` exactly, because those slots map to real values the skill uses at runtime.

Or take this dialog line:

```
It is {temp} degrees {condition} in {location}
```

That's what the skill *says* when it reports the weather. You need at least two variants so the assistant doesn't sound like a broken record. `{condition}` will be values like "sunny" or "overcast" — so your translation needs to handle those gracefully too.

The previous tool we used — GitLocalize — didn't know any of this. Translators saw files line by line, with no context about what each line was for, what triggered it, or what the slots meant. The result was translations that were grammatically correct but functionally broken. A dialog line with a missing `{variable}` doesn't render; it crashes the skill response. An intent file with one sentence doesn't train reliably; the skill stops recognising the user.

## The Idea: GitHub Is Already the Platform

We had a choice: build infrastructure, or build *on top of* infrastructure that already exists.

GitHub already has everything we need:

- **GitHub Pages** serves static files globally, for free, with a CDN.
- **GitHub Issues** is a structured form submission system with webhook triggers.
- **GitHub Actions** is a workflow engine that runs in response to events.
- **GitHub Apps** can issue short-lived, repository-scoped tokens without storing user credentials.
- **Pull Requests** give skill maintainers a review step before anything lands in their repo.

So that's what OVOS Localize is: a static single-page app on GitHub Pages, reading from JSON files in the same repo, with four GitHub Actions workflows handling all the automation. No servers. No databases. No Docker. No cloud bill.

When you submit a translation, you're opening a GitHub Issue. A workflow reads the issue body, generates a short-lived token scoped to the target skill repo, creates a branch, commits your translation, opens a PR, and closes the issue — all within seconds. The skill maintainer reviews the PR. That's it. You need nothing but a GitHub account.

## How It Works (Three Minutes)

**1. Start at the dashboard.** A heatmap shows all 57 tracked skills against 30 languages, colour-coded by translation coverage. Dark means complete. Light means someone needs to help.

**2. Pick a skill.** Click any skill to see its files, which languages are covered, and which have validation issues. You can filter by file type.

**3. Open the editor.** A three-panel view: the English source on the left, your translation in the middle, and a context card on the right. The context card shows the Python handler that uses this file — the actual method source — along with the slots it expects, the intents connected to it, and what the skill does when it speaks these lines. You're not translating blind.

**4. Submit.** Click "Submit as PR". A GitHub Issue opens, pre-filled with everything the bot needs. Sign in, submit. Done.

**5. The bot takes over.** Within seconds, `ovos-localize[bot]` opens a pull request on the skill repo. The maintainer reviews and merges.

Every step is tracked in git. Every contribution is attributable. Every PR goes through the normal review process.

## Under the Hood

A Python data pipeline runs daily at 02:00 UTC. It clones all 57 skill repos (shallow, cached), scans their locale directories, parses 2,252 locale files across 8 distinct file types, runs over 15 validation rules, walks the Python source with AST analysis to extract handler connections, and writes everything to static JSON files. Then it commits the results and GitHub Pages serves them immediately.

Eight file types. Eight parsers. Eight sets of validation rules. Each type has different requirements:

- `.intent` files need at least 10 training sentences with sufficient lexical diversity
- `.dialog` files need at least 2 variants and must preserve `{variable}` substitutions
- `.entity` files need at least 5 examples for reliable slot filling
- `.voc` files are keyword lists — short entries, no multi-line values

If a translation violates any of these, the editor tells you before you submit. And if a skill's translations fail validation after the fact, it shows up in the Issues view.

The context cards come from real Python AST analysis. When the pipeline sees `self.speak_dialog("query_weather")` in a skill method decorated with `@intent_handler`, it connects that dialog file to that handler and stores the source. When you open the editor, you see it.

For a deeper dive into the architecture, see the [technical whitepaper](whitepaper.md).

## The Issues View

Translations aren't the only thing that can be wrong. Some skills have locale directories named `eu` or `da` instead of `eu-ES` or `da-DK` — bare language codes without a region subtag. These are technically unambiguous in the OVOS context (Basque is always `eu-ES`; Danish is always `da-DK`), but they confuse tools that expect full BCP-47 codes and they look wrong in coverage statistics.

These are mechanical renames. So we automated them.

The Issues view has a "Developer Issues" tab that lists all 109 bare-code warnings across the tracked skills. Each one has a "Request Auto-Fix" button. Click it, confirm the GitHub Issue, and a workflow checks out the skill repo, renames the locale directories, and opens a PR — all without any manual file editing.

There's also a "Translation Quality" tab for community contributors. It shows validation rule violations by skill and language — things like intent files with too few training sentences, or dialog files missing required variables. Each issue has a "Report" button that opens a pre-filled issue in the skill's own repository, complete with a table showing exactly which files and which lines are affected. Skill maintainers see a structured bug report; translators don't have to manually describe what's wrong.

## Your Translations Become Open Data

Here's a side effect we're proud of: every translation contributed through OVOS Localize automatically becomes part of a free, open ML dataset.

The same pipeline that generates the editor data also generates six dataset formats:

- **Intent classification** — (utterance, skill, intent) triples for training intent classifiers
- **Parallel translation** — English ↔ target language pairs for translation model fine-tuning
- **Slot filling** — templates, slot names, and entity values for NER training
- **Response pairs** — (utterance, response) pairs for dialogue model training
- **TTS corpus** — deduplicated dialog sentences for training speech synthesis models
- **Skill metadata** — multilingual skill names and descriptions for discovery

These datasets are committed to the repo daily, split at 100 MB for GitHub compatibility, and loadable via HuggingFace Datasets. The more languages get translated, the richer the datasets.

## Help Us Localise OVOS

Here's where you can help:

- **Translate skills** at [openvoiceos.github.io/ovos-localize](https://openvoiceos.github.io/ovos-localize/). Filter by your language on the dashboard, pick a skill with low coverage, and start translating.

- **Check the Issues view** for your language. Low-diversity intent files and missing dialog variants are easy to fix if you're a native speaker.

- **Add your skill** by opening a PR to add your `org/repo` to [`skills.txt`](https://github.com/OpenVoiceOS/ovos-localize/blob/dev/skills.txt). The pipeline picks it up automatically on the next daily run.

- **Request a new language** via the "Can't find your language?" link in the language selector. A workflow opens a PR to add it to the enabled list.

No infrastructure to set up. No admin to email. Just GitHub.
