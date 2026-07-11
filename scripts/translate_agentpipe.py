"""Translate missing .intent patterns to all languages using agentpipe free cascade.

SCOPE — read this first. This produces **ML training data only** (the intent
classification corpora under data/datasets/), never official translations.
Machine-translated text must NEVER be submitted as a skill's locale files:
those are always written by human translators through the editor + review flow.
The only consumer of this output is dataset generation for intent training.

Resumable: progress is tracked in data/datasets/classification/.progress/<lang>.json
(set of completed "skill::intent" keys). Rows are written immediately after each
intent batch so a kill never loses more than one batch.

Usage:
    python3 scripts/translate_agentpipe.py              # fill all languages
    python3 scripts/translate_agentpipe.py --lang de-DE # single language
    python3 scripts/translate_agentpipe.py --status     # show progress report
    python3 scripts/translate_agentpipe.py --dry-run    # no writes, no agent calls
    python3 scripts/translate_agentpipe.py --upload     # push result to HF after done
    python3 scripts/translate_agentpipe.py --concurrency 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SLOT_RE = re.compile(r"\{[^}]+\}|<[^>]+>")
DATA_DIR = Path("data/datasets/classification")
PROGRESS_DIR = DATA_DIR / ".progress"
HF_REPO_TRANSLATED = "OpenVoiceOS/ovos-localize-intents-translated"
DEFAULT_CONCURRENCY = 4

LANG_LABELS: dict[str, str] = {
    "ca-ES": "Catalan (ca-ES)",
    "cs-CZ": "Czech (cs-CZ)",
    "da-DK": "Danish (da-DK)",
    "de-DE": "German (de-DE)",
    "el-GR": "Greek (el-GR)",
    "es-ES": "Spanish (es-ES)",
    "eu-ES": "Basque (eu-ES)",
    "fa-IR": "Persian / Farsi (fa-IR)",
    "fr-FR": "French (fr-FR)",
    "gl-ES": "Galician (gl-ES)",
    "hu-HU": "Hungarian (hu-HU)",
    "it-IT": "Italian (it-IT)",
    "nl-BE": "Dutch / Belgian (nl-BE)",
    "nl-NL": "Dutch (nl-NL)",
    "pl-PL": "Polish (pl-PL)",
    "pt-BR": "Brazilian Portuguese (pt-BR)",
    "pt-PT": "European Portuguese (pt-PT)",
    "ro-RO": "Romanian (ro-RO)",
    "ru-RU": "Russian (ru-RU)",
    "sv-FI": "Swedish / Finland (sv-FI)",
    "sv-SE": "Swedish (sv-SE)",
    "tr-TR": "Turkish (tr-TR)",
    "uk-UA": "Ukrainian (uk-UA)",
    "az-AZ": "Azerbaijani (az-AZ)",
    "lt-LT": "Lithuanian (lt-LT)",
    "fi-FI": "Finnish (fi-FI)",
    "nb-NO": "Norwegian Bokmål (nb-NO)",
    "hr-HR": "Croatian (hr-HR)",
    "sk-SK": "Slovak (sk-SK)",
    "sl-SI": "Slovenian (sl-SI)",
    "bg-BG": "Bulgarian (bg-BG)",
}

# Languages intentionally excluded from machine translation — the free-tier
# agentpipe cascade (see free_model_list()) has little to no training signal
# for these, so MT output would be unreliable and risks anchoring human
# translators to a bad suggestion. These languages are human-first: enabled
# for manual translation in the SPA, with no MT-suggestion affordance.
# Kept as an explicit set (rather than relying on omission from LANG_LABELS)
# so the exclusion is documented and a future addition of the language to
# LANG_LABELS doesn't accidentally start machine-translating it.
LOW_RESOURCE_LANGS: frozenset[str] = frozenset({"kab"})  # Kabyle — issue #208


# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

def _progress_path(lang: str) -> Path:
    return PROGRESS_DIR / f"{lang}.json"


def load_progress(lang: str) -> set[str]:
    """Return set of completed 'skill::intent' keys for this language."""
    p = _progress_path(lang)
    if p.exists():
        return set(json.loads(p.read_text()))
    return set()


def save_progress(lang: str, done: set[str]) -> None:
    PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    _progress_path(lang).write_text(json.dumps(sorted(done)))


# ---------------------------------------------------------------------------
# Slot validation
# ---------------------------------------------------------------------------

def slots_ok(original: str, translated: str) -> bool:
    return sorted(SLOT_RE.findall(original)) == sorted(SLOT_RE.findall(translated))


# ---------------------------------------------------------------------------
# Prompt + cascade call
# ---------------------------------------------------------------------------

def make_prompt(lang_label: str, intent_name: str, utterances: list[str]) -> str:
    items = json.dumps(utterances, ensure_ascii=False)
    has_slots = any(SLOT_RE.search(u) for u in utterances)
    slot_rule = (
        "\n3. Preserve ALL template tokens EXACTLY as written — do not translate them:\n"
        "   - {slot_name}  (Padatious slot, curly braces)\n"
        "   - <EntityName> (Adapt entity reference, angle brackets)\n"
        "   Copy these tokens character-for-character into the translated string."
        if has_slots else ""
    )
    n = len(utterances)
    return (
        f"You are localizing an open-source voice assistant (OpenVoiceOS).\n"
        f"Translate the following {n} utterance(s) to {lang_label}.\n"
        f"Intent: {intent_name}\n\n"
        f"Rules:\n"
        f"1. Translate ONLY the natural-language words — keep the same meaning and register.\n"
        f"2. Return a valid JSON array of exactly {n} translated strings, in the same order."
        f"{slot_rule}\n"
        f"4. Output ONLY the JSON array — no markdown, no explanation.\n\n"
        f"Input:\n{items}\n\nOutput:"
    )


async def call_cascade(prompt: str) -> list[str] | None:
    from agentpipe import cascade_free_only
    result = await cascade_free_only(prompt)
    if not result or not result.successful_model:
        return None
    text = result.text or ""
    text = re.sub(r"^```[^\n]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text.strip())
    try:
        parsed = json.loads(text)
        return [str(t) for t in parsed] if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Per-language fill
# ---------------------------------------------------------------------------

async def fill_language(
    lang: str,
    lang_label: str,
    en_by_intent: dict[tuple[str, str], list[dict]],
    data_dir: Path,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        out_path = data_dir / f"{lang}.jsonl"
        done_keys = load_progress(lang)

        # Build existing (skill, intent) pairs from file (for intents only)
        existing: set[tuple[str, str]] = set()
        if out_path.exists():
            with open(out_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        r = json.loads(line)
                        if r.get("file_type") == "intent":
                            existing.add((r["skill"], r["intent"]))

        missing_keys = [k for k in en_by_intent if k not in existing]
        # Also skip keys already completed in a prior interrupted run
        todo_keys = [k for k in missing_keys if f"{k[0]}::{k[1]}" not in done_keys]
        total_utts = sum(len(en_by_intent[k]) for k in todo_keys)

        print(
            f"[{lang}] {len(todo_keys)}/{len(en_by_intent)} intents remaining "
            f"({total_utts} utterances)"
        )

        if dry_run or not todo_keys:
            return {"lang": lang, "written": 0, "failed": 0}

        written = failed = 0

        with open(out_path, "a", encoding="utf-8") as fout:
            for i, key in enumerate(todo_keys):
                skill, intent = key
                en_rows = en_by_intent[key]
                originals = [r["text"] for r in en_rows]

                translations = await call_cascade(
                    make_prompt(lang_label, intent, originals)
                )

                if translations is None or len(translations) != len(originals):
                    failed += 1
                    # Fall back to en-US text
                    translations = originals

                for orig_row, trans_text in zip(en_rows, translations):
                    if not slots_ok(orig_row["text"], trans_text):
                        trans_text = orig_row["text"]
                    fout.write(json.dumps({
                        "lang": lang,
                        "skill": orig_row["skill"],
                        "file_type": "intent",
                        "intent": orig_row["intent"],
                        "text": trans_text,
                    }, ensure_ascii=False) + "\n")
                    written += 1

                # Mark this intent done and persist immediately
                done_keys.add(f"{skill}::{intent}")
                save_progress(lang, done_keys)

                if (i + 1) % 25 == 0 or (i + 1) == len(todo_keys):
                    pct = int((i + 1) / len(todo_keys) * 100)
                    print(f"[{lang}] {pct}% — {i+1}/{len(todo_keys)} intents, "
                          f"{written} rows written")

        print(f"[{lang}] DONE — {written} rows, {failed} fallbacks")
        return {"lang": lang, "written": written, "failed": failed}


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(
    en_by_intent: dict[tuple[str, str], list[dict]],
    data_dir: Path,
    langs: list[str],
) -> None:
    total_intents = len(en_by_intent)
    total_utts = sum(len(v) for v in en_by_intent.values())
    print(f"en-US baseline: {total_intents} intents, {total_utts} utterances\n")
    print(f"{'lang':<12} {'progress':>16}  {'intents done':>13}  {'rows in file':>13}")
    print("-" * 60)
    for lang in langs:
        done_keys = load_progress(lang)
        path = data_dir / f"{lang}.jsonl"
        file_rows = 0
        if path.exists():
            with open(path) as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        if r.get("file_type") == "intent":
                            file_rows += 1
        done = len(done_keys)
        pct = int(done / total_intents * 100) if total_intents else 0
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        print(f"{lang:<12} [{bar}] {pct:>3}%  {done:>5}/{total_intents}  {file_rows:>13,}")


# ---------------------------------------------------------------------------
# HF upload
# ---------------------------------------------------------------------------

def upload_translated(data_dir: Path, langs: list[str]) -> None:
    import csv, io
    from huggingface_hub import HfApi

    rows = []
    covered_langs = []
    for lang in langs:
        path = data_dir / f"{lang}.jsonl"
        if not path.exists():
            continue
        lang_rows = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    if r.get("file_type") == "intent":
                        lang_rows.append({
                            "lang": r["lang"],
                            "domain": r["skill"],
                            "intent": r["intent"],
                            "sentence": r["text"],
                        })
        if lang_rows:
            rows.extend(lang_rows)
            covered_langs.append(lang)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["lang", "domain", "intent", "sentence"])
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = buf.getvalue().encode()

    lang_list = "\n".join(f"- {l.split('-')[0]}" for l in sorted(set(l.split('-')[0] for l in covered_langs)))
    card = f"""\
---
language:
{lang_list}
task_categories:
- text-classification
pretty_name: OpenVoiceOS Localize — Machine-Translated Intent Dataset
license: apache-2.0
tags:
- ovos
- voice-assistant
- intent-classification
- nlu
- multilingual
- machine-translation
source_datasets:
- OpenVoiceOS/ovos-localize-intents
---

# OpenVoiceOS Localize — Machine-Translated Intent Dataset

Gap-filled version of
[OpenVoiceOS/ovos-localize-intents](https://huggingface.co/datasets/OpenVoiceOS/ovos-localize-intents):
every `.intent` pattern present in `en-US` but missing from a given language
has been machine-translated using the
[agentpipe](https://github.com/TigreGotico/agentpipe) free-tier cascade
(opencode/big-pickle → antigravity → gemini-2.5-flash).

Template tokens (`{{slot_name}}`, `<EntityName>`) are preserved verbatim.
Rows where slot preservation failed fall back to the en-US source string.

## Schema

| Column   | Description |
|----------|-------------|
| `lang`   | BCP-47 locale code |
| `domain` | OVOS skill id |
| `intent` | Source `.intent` filename |
| `sentence` | Utterance (human translation where available, MT otherwise) |

## Collection

Part of the
[OpenVoiceOS intent-classification-datasets](https://huggingface.co/collections/OpenVoiceOS/intent-classification-datasets)
collection.
"""

    api = HfApi()
    api.create_repo(HF_REPO_TRANSLATED, repo_type="dataset", exist_ok=True, private=True)
    api.upload_file(
        path_or_fileobj=csv_bytes,
        path_in_repo="ovos_localize_intents_translated.csv",
        repo_id=HF_REPO_TRANSLATED,
        repo_type="dataset",
        commit_message="chore: refresh translated dataset",
    )
    api.upload_file(
        path_or_fileobj=card.encode(),
        path_in_repo="README.md",
        repo_id=HF_REPO_TRANSLATED,
        repo_type="dataset",
        commit_message="chore: update dataset card",
    )
    print(f"Uploaded {len(rows):,} rows ({len(covered_langs)} langs) to "
          f"https://huggingface.co/datasets/{HF_REPO_TRANSLATED}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> None:
    if args.lang in LOW_RESOURCE_LANGS:
        sys.exit(
            f"{args.lang} is a human-first language (LOW_RESOURCE_LANGS) — "
            "machine translation is intentionally not available for it. "
            "Translate directly in the SPA instead."
        )

    data_dir = Path(args.data_dir)
    en_path = data_dir / "en-US.jsonl"
    if not en_path.exists():
        sys.exit(f"en-US.jsonl not found in {data_dir}")

    en_by_intent: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with open(en_path) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("file_type") == "intent":
                    en_by_intent[(r["skill"], r["intent"])].append(r)

    target_langs = (
        [args.lang] if args.lang
        else [l for l in LANG_LABELS if l != "en-US"]
    )

    if args.status:
        print_status(en_by_intent, data_dir, target_langs)
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [
        fill_language(lang, LANG_LABELS[lang], en_by_intent, data_dir,
                      args.dry_run, semaphore)
        for lang in target_langs
        if lang in LANG_LABELS
    ]
    results = await asyncio.gather(*tasks)

    total_written = sum(r["written"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    print(f"\nDone: {total_written:,} rows written, {total_failed} fallbacks.")

    if args.upload:
        upload_translated(data_dir, list(LANG_LABELS.keys()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/datasets/classification")
    # LOW_RESOURCE_LANGS is included in choices (not just LANG_LABELS) so a
    # low-resource language hits the friendly guard message in main_async
    # instead of argparse's generic "invalid choice" error.
    parser.add_argument(
        "--lang", choices=list(LANG_LABELS) + list(LOW_RESOURCE_LANGS), default=None
    )
    parser.add_argument("--status", action="store_true",
                        help="Show per-language progress and exit")
    parser.add_argument("--upload", action="store_true",
                        help="Upload translated dataset to HF after finishing")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
