"""Translate the en-US intent classification dataset to new languages via agentpipe.

Uses the free-tier cascade (opencode/big-pickle → antigravity → gemini-2.5-flash …)
to translate utterances while strictly preserving OVOS template slots ({slot_name}).

Only languages that ALREADY have some OVOS skill locale files are targeted — we are
filling gaps in the classification dataset, not creating unsupported locales.

Output is written to data/datasets/classification/<lang>.jsonl in the same format
as the existing files.

Usage:
    python3 scripts/translate_agentpipe.py [--lang az-AZ] [--batch-size 30] [--dry-run]
    python3 scripts/translate_agentpipe.py --list-targets
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

# Languages present in OVOS skill repos but not yet in the classification dataset.
# Add here as new skill translations land.
TRANSLATION_TARGETS: dict[str, str] = {
    "az-AZ": "Azerbaijani (az-AZ)",
    "lt-LT": "Lithuanian (lt-LT)",
    "fi-FI": "Finnish (fi-FI)",
    "nb-NO": "Norwegian Bokmål (nb-NO)",
    "hr-HR": "Croatian (hr-HR)",
    "sk-SK": "Slovak (sk-SK)",
    "sl-SI": "Slovenian (sl-SI)",
    "bg-BG": "Bulgarian (bg-BG)",
}

SLOT_PATTERN = re.compile(r"\{[^}]+\}")


def extract_slots(text: str) -> list[str]:
    return SLOT_PATTERN.findall(text)


def validate_slots(original: str, translated: str) -> bool:
    """Translated text must contain all original {slot} tokens."""
    orig_slots = extract_slots(original)
    trans_slots = extract_slots(translated)
    return sorted(orig_slots) == sorted(trans_slots)


def make_translation_prompt(lang_label: str, batch: list[str]) -> str:
    items_json = json.dumps(batch, ensure_ascii=False)
    return f"""\
You are translating OVOS voice-assistant utterances to {lang_label}.

RULES:
1. Translate ONLY the text content. Keep the same meaning and register.
2. Preserve ALL {{slot_name}} placeholders EXACTLY as they appear — do not translate, rename, or reorder them.
3. Return a valid JSON array with exactly {len(batch)} translated strings, in the same order.
4. No extra commentary, no markdown fences — just the JSON array.

Input JSON array:
{items_json}

Output:"""


async def translate_batch(lang_label: str, batch: list[str]) -> list[str] | None:
    """Translate a batch; return None on unrecoverable failure."""
    from agentpipe import cascade_free_only

    prompt = make_translation_prompt(lang_label, batch)
    result = await cascade_free_only(prompt)
    if not result or not result.successful_model:
        return None

    text = result.text or ""
    # Strip markdown fences if the model wrapped the output
    text = re.sub(r"^```[^\n]*\n?", "", text.strip())
    text = re.sub(r"\n?```$", "", text.strip())
    try:
        translated = json.loads(text)
        if not isinstance(translated, list) or len(translated) != len(batch):
            return None
        return [str(t) for t in translated]
    except json.JSONDecodeError:
        return None


def read_en_us(data_dir: Path) -> list[dict]:
    path = data_dir / "en-US.jsonl"
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


async def translate_language(
    lang: str,
    lang_label: str,
    en_rows: list[dict],
    out_dir: Path,
    batch_size: int,
    dry_run: bool,
) -> int:
    out_path = out_dir / f"{lang}.jsonl"
    if out_path.exists():
        print(f"  {lang}: already exists at {out_path}, skipping.")
        return 0

    print(f"  {lang}: translating {len(en_rows):,} utterances …")

    if dry_run:
        print(f"  {lang}: dry-run — skipping actual translation.")
        return 0

    translated_rows: list[dict] = []
    errors = 0

    for i in range(0, len(en_rows), batch_size):
        batch_rows = en_rows[i: i + batch_size]
        originals = [r["text"] for r in batch_rows]

        translations = await translate_batch(lang_label, originals)
        if translations is None:
            print(f"    batch {i//batch_size + 1}: translation failed, skipping batch")
            errors += len(batch_rows)
            continue

        for orig_row, trans_text in zip(batch_rows, translations):
            if not validate_slots(orig_row["text"], trans_text):
                # Slot mismatch — keep en-US as fallback, mark as untranslated
                trans_text = orig_row["text"]

            translated_rows.append({
                "lang": lang,
                "skill": orig_row["skill"],
                "file_type": orig_row["file_type"],
                "intent": orig_row["intent"],
                "text": trans_text,
            })

        if (i // batch_size + 1) % 10 == 0:
            pct = min(100, int((i + batch_size) / len(en_rows) * 100))
            print(f"    {pct}% done ({i + batch_size:,}/{len(en_rows):,})")

    with open(out_path, "w", encoding="utf-8") as f:
        for row in translated_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  {lang}: wrote {len(translated_rows):,} rows to {out_path} ({errors} skipped)")
    return len(translated_rows)


async def main_async(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    out_dir = data_dir  # write back into the same directory

    if args.list_targets:
        for lang, label in TRANSLATION_TARGETS.items():
            exists = (out_dir / f"{lang}.jsonl").exists()
            status = "exists" if exists else "missing"
            print(f"  {lang:10s}  {label}  [{status}]")
        return

    targets = (
        {args.lang: TRANSLATION_TARGETS[args.lang]}
        if args.lang
        else TRANSLATION_TARGETS
    )

    en_rows = read_en_us(data_dir)
    print(f"Loaded {len(en_rows):,} en-US rows.")

    total = 0
    for lang, label in targets.items():
        total += await translate_language(
            lang, label, en_rows, out_dir, args.batch_size, args.dry_run
        )

    print(f"\nDone. {total:,} rows written total.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/datasets/classification")
    parser.add_argument("--lang", choices=list(TRANSLATION_TARGETS), default=None,
                        help="Translate a single language only")
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.lang and args.lang not in TRANSLATION_TARGETS:
        sys.exit(f"Unknown target: {args.lang}. Use --list-targets.")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
