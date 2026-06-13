"""Export ovos-localize classification datasets to HuggingFace.

Reads all per-language JSONL files from data/datasets/classification/,
converts to the collection-standard CSV format (lang,domain,intent,sentence),
and uploads to OpenVoiceOS/ovos-localize-intents on HF.

Usage:
    python3 scripts/export_hf.py [--data-dir data/datasets/classification] [--dry-run]
"""

import argparse
import csv
import io
import json
import os
from pathlib import Path

from huggingface_hub import HfApi


REPO_ID = "OpenVoiceOS/ovos-localize-intents"

DATASET_CARD = """\
---
language:
{lang_list}
task_categories:
- text-classification
pretty_name: OpenVoiceOS Localize — Intent Classification Dataset
license: apache-2.0
size_categories:
- 100K<n<1M
tags:
- ovos
- voice-assistant
- intent-classification
- nlu
- multilingual
source_datasets:
- OpenVoiceOS/OVOSGitLocalize-Intents
---

# OpenVoiceOS Localize — Intent Classification Dataset

Multilingual intent classification corpus exported from
[OpenVoiceOS/ovos-localize](https://github.com/OpenVoiceOS/ovos-localize).

Each row is a single expanded utterance labelled with the OVOS skill and
intent file that produced it.  Templates are fully expanded (bracket
alternation resolved); `{{slot_name}}` placeholders from `.intent` files are
kept verbatim so models can learn the slot-carrying pattern.

## Schema

| Column   | Description |
|----------|-------------|
| `lang`   | BCP-47 locale code (`en-US`, `pt-PT`, …) |
| `domain` | OVOS skill id (`ovos-skill-hello-world`, …) |
| `intent` | Source filename (`HelloWorldKeyword.voc`, `HowAreYou.intent`, …) |
| `sentence` | Expanded, cleaned utterance text |

## Languages

{lang_lines}

## Data source

Generated daily by the
[ovos-localize](https://github.com/OpenVoiceOS/ovos-localize) data pipeline
from live OVOS skill repositories.

## Collection

Part of the
[OpenVoiceOS intent-classification-datasets](https://huggingface.co/collections/OpenVoiceOS/intent-classification-datasets)
collection.
"""


def read_jsonl_dir(data_dir: Path) -> list[dict]:
    rows = []
    for jsonl_file in sorted(data_dir.glob("*.jsonl")):
        with open(jsonl_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("file_type") != "intent":
                    continue
                rows.append({
                    "lang": rec["lang"],
                    "domain": rec["skill"],
                    "intent": rec["intent"],
                    "sentence": rec["text"],
                })
    return rows


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["lang", "domain", "intent", "sentence"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def build_card(langs: list[str]) -> str:
    lang_list = "\n".join(f"- {l.split('-')[0]}" for l in sorted(set(l.split('-')[0] for l in langs)))
    lang_lines = "\n".join(f"- `{l}`" for l in sorted(langs))
    return DATASET_CARD.format(lang_list=lang_list, lang_lines=lang_lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/datasets/classification")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"Data directory not found: {data_dir}")

    print(f"Reading JSONL files from {data_dir} …")
    rows = read_jsonl_dir(data_dir)
    print(f"  {len(rows):,} rows across {len(set(r['lang'] for r in rows))} languages")

    langs = sorted(set(r["lang"] for r in rows))
    csv_content = rows_to_csv(rows)
    card = build_card(langs)

    if args.dry_run:
        print("Dry-run — not uploading.")
        print(f"  CSV bytes: {len(csv_content):,}")
        print(f"  Languages: {langs}")
        return

    api = HfApi()
    api.create_repo(REPO_ID, repo_type="dataset", exist_ok=True, private=True)

    api.upload_file(
        path_or_fileobj=csv_content.encode(),
        path_in_repo="ovos_localize_intents.csv",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="chore: refresh dataset from ovos-localize",
    )
    api.upload_file(
        path_or_fileobj=card.encode(),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="chore: update dataset card",
    )
    print(f"Uploaded to https://huggingface.co/datasets/{REPO_ID}")


if __name__ == "__main__":
    main()
