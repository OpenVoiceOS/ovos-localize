#!/usr/bin/env python3
"""Generate ML datasets from parsed OVOS skill JSON files.

Reads from ``data/skills/`` and outputs JSONL datasets to ``data/datasets/``.
Includes intent classification and parallel corpora for machine translation.
"""

import json
import sys
from pathlib import Path
from typing import Dict, TextIO

# Setup paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
DATASETS_DIR = DATA_DIR / "datasets"

# Add repo root to path to import ovos_localize
sys.path.insert(0, str(REPO_ROOT))

from ovos_localize.datasets import generate_intent_classification, generate_parallel_corpora


def main():
    """Main generation routine."""
    if not SKILLS_DIR.exists():
        print(f"Error: {SKILLS_DIR} not found. Run generate_data.py first.")
        sys.exit(1)

    cls_dir = DATASETS_DIR / "classification"
    tra_dir = DATASETS_DIR / "translation"
    cls_dir.mkdir(parents=True, exist_ok=True)
    tra_dir.mkdir(parents=True, exist_ok=True)

    cls_files: Dict[str, TextIO] = {}
    tra_files: Dict[str, TextIO] = {}

    def get_cls_file(lang: str) -> TextIO:
        if lang not in cls_files:
            cls_files[lang] = open(cls_dir / f"{lang}.jsonl", "w", encoding="utf-8")
        return cls_files[lang]

    def get_tra_file(pair: str) -> TextIO:
        if pair not in tra_files:
            tra_files[pair] = open(tra_dir / f"{pair}.jsonl", "w", encoding="utf-8")
        return tra_files[pair]

    try:
        for skill_file in sorted(SKILLS_DIR.glob("*.json")):
            skill_id = skill_file.stem
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    skill_data = json.load(f)
            except Exception as e:
                print(f"Failed to load {skill_file}: {e}")
                continue

            # 1. Classification
            for sample in generate_intent_classification(skill_id, skill_data):
                lang = sample.get("lang")
                if lang:
                    f_out = get_cls_file(lang)
                    f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")

            # 2. Translation (Parallel Corpora)
            for sample in generate_parallel_corpora(skill_id, skill_data):
                pair = sample.get("pair")
                if pair:
                    f_out = get_tra_file(pair)
                    f_out.write(json.dumps(sample, ensure_ascii=False) + "\n")

    finally:
        for f in cls_files.values():
            f.close()
        for f in tra_files.values():
            f.close()

    print(f"Datasets generated successfully in {DATASETS_DIR}")

if __name__ == "__main__":
    main()
