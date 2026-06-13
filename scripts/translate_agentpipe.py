"""Translate missing intents in every language's classification dataset.

For each non-en-US language, finds (skill, intent) pairs that exist in en-US
but not in that language, then translates those utterances via the agentpipe
free-tier cascade and appends them to the existing JSONL file.

Translations are grouped by (skill, intent) so the model has semantic context.
OVOS template slots ({slot_name}) are preserved exactly per the OVOS locale spec.

Usage:
    # Fill all languages
    python3 scripts/translate_agentpipe.py

    # Fill a single language
    python3 scripts/translate_agentpipe.py --lang de-DE

    # Show gaps without translating
    python3 scripts/translate_agentpipe.py --report

    # Dry-run (no writes, no agent calls)
    python3 scripts/translate_agentpipe.py --dry-run

    # Limit concurrent translation jobs (default: 4)
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

# Matches both Padatious slots ({slot_name}) and Adapt entity refs (<EntityName>)
SLOT_RE = re.compile(r"\{[^}]+\}|<[^>]+>")
DATA_DIR = Path("data/datasets/classification")
CONCURRENCY = 4  # parallel languages at once


# ---------------------------------------------------------------------------
# Slot validation
# ---------------------------------------------------------------------------

def slots_ok(original: str, translated: str) -> bool:
    return sorted(SLOT_RE.findall(original)) == sorted(SLOT_RE.findall(translated))


# ---------------------------------------------------------------------------
# Prompt construction
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


# ---------------------------------------------------------------------------
# Translation call
# ---------------------------------------------------------------------------

async def call_cascade(prompt: str) -> str | None:
    from agentpipe import cascade_free_only
    result = await cascade_free_only(prompt)
    if not result or not result.successful_model:
        return None
    text = result.text or ""
    text = re.sub(r"^```[^\n]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text.strip())
    return text or None


async def translate_intent_batch(
    lang_label: str, intent_name: str, utterances: list[str]
) -> list[str] | None:
    """Translate one intent's utterances. Returns None on failure."""
    prompt = make_prompt(lang_label, intent_name, utterances)
    raw = await call_cascade(prompt)
    if raw is None:
        return None
    try:
        result = json.loads(raw)
        if not isinstance(result, list) or len(result) != len(utterances):
            return None
        return [str(t) for t in result]
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Per-language gap filling
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

        # Load existing (skill, intent) pairs
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
        total_utterances = sum(len(en_by_intent[k]) for k in missing_keys)

        print(
            f"[{lang}] {len(missing_keys)} missing intents, "
            f"{total_utterances} utterances to translate"
        )

        if dry_run or not missing_keys:
            return {"lang": lang, "translated": 0, "skipped": 0, "failed_intents": 0}

        translated_rows: list[dict] = []
        failed_intents = 0
        skipped_rows = 0

        for i, key in enumerate(missing_keys):
            skill, intent = key
            en_rows = en_by_intent[key]
            originals = [r["text"] for r in en_rows]

            translations = await translate_intent_batch(lang_label, intent, originals)

            if translations is None:
                failed_intents += 1
                # Fall back: keep en-US text
                for r in en_rows:
                    translated_rows.append({
                        "lang": lang,
                        "skill": r["skill"],
                        "file_type": r["file_type"],
                        "intent": r["intent"],
                        "text": r["text"],
                    })
                skipped_rows += len(en_rows)
                continue

            for orig_row, trans_text in zip(en_rows, translations):
                if not slots_ok(orig_row["text"], trans_text):
                    trans_text = orig_row["text"]
                    skipped_rows += 1
                translated_rows.append({
                    "lang": lang,
                    "skill": orig_row["skill"],
                    "file_type": orig_row["file_type"],
                    "intent": orig_row["intent"],
                    "text": trans_text,
                })

            if (i + 1) % 50 == 0 or (i + 1) == len(missing_keys):
                pct = int((i + 1) / len(missing_keys) * 100)
                print(f"[{lang}] {pct}% ({i + 1}/{len(missing_keys)} intents)")

        # Append (or create) the file
        mode = "a" if out_path.exists() else "w"
        with open(out_path, mode, encoding="utf-8") as f:
            for row in translated_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        n = len(translated_rows)
        print(
            f"[{lang}] done — wrote {n} rows "
            f"({failed_intents} failed intents, {skipped_rows} slot-fallbacks)"
        )
        return {
            "lang": lang,
            "translated": n - skipped_rows,
            "skipped": skipped_rows,
            "failed_intents": failed_intents,
        }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(
    en_by_intent: dict[tuple[str, str], list[dict]], data_dir: Path, langs: list[str]
) -> None:
    en_keys = set(en_by_intent)
    print(f"{'lang':<12} {'rows':>7}  {'missing intents':>15}  {'missing utterances':>18}")
    print("-" * 60)
    for lang in langs:
        path = data_dir / f"{lang}.jsonl"
        existing: set[tuple[str, str]] = set()
        count = 0
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        r = json.loads(line)
                        existing.add((r["skill"], r["intent"]))
                        count += 1
        missing_keys = en_keys - existing
        missing_utts = sum(len(en_by_intent[k]) for k in missing_keys)
        print(f"{lang:<12} {count:>7}  {len(missing_keys):>15}  {missing_utts:>18}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
    # Languages with OVOS skill files but no classification dataset yet
    "az-AZ": "Azerbaijani (az-AZ)",
    "lt-LT": "Lithuanian (lt-LT)",
    "fi-FI": "Finnish (fi-FI)",
    "nb-NO": "Norwegian Bokmål (nb-NO)",
    "hr-HR": "Croatian (hr-HR)",
    "sk-SK": "Slovak (sk-SK)",
    "sl-SI": "Slovenian (sl-SI)",
    "bg-BG": "Bulgarian (bg-BG)",
}


async def main_async(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)

    # Build en-US index: (skill, intent) -> [row, ...]
    en_path = data_dir / "en-US.jsonl"
    if not en_path.exists():
        sys.exit(f"en-US.jsonl not found in {data_dir}")

    en_by_intent: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with open(en_path) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("file_type") != "intent":
                    continue
                en_by_intent[(r["skill"], r["intent"])].append(r)

    print(f"en-US: {sum(len(v) for v in en_by_intent.values()):,} utterances, "
          f"{len(en_by_intent)} unique intents")

    target_langs = (
        [args.lang] if args.lang else [l for l in LANG_LABELS if l != "en-US"]
    )

    if args.report:
        print_report(en_by_intent, data_dir, target_langs)
        return

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [
        fill_language(lang, LANG_LABELS[lang], en_by_intent, data_dir,
                      args.dry_run, semaphore)
        for lang in target_langs
        if lang in LANG_LABELS
    ]
    results = await asyncio.gather(*tasks)

    total_translated = sum(r["translated"] for r in results)
    total_failed = sum(r["failed_intents"] for r in results)
    print(f"\nFinished: {total_translated:,} rows translated, "
          f"{total_failed} intent batches failed.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/datasets/classification")
    parser.add_argument("--lang", choices=list(LANG_LABELS), default=None)
    parser.add_argument("--report", action="store_true",
                        help="Print gap report without translating")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
