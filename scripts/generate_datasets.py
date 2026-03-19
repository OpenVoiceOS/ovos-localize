#!/usr/bin/env python3
"""Generate ML datasets from parsed OVOS skill JSON files.

Reads from ``data/skills/`` and outputs JSONL datasets to ``data/datasets/``.
Includes intent classification and parallel corpora for machine translation.
"""

import json
import sys
import os
from pathlib import Path
from typing import Dict, TextIO, Optional

# Setup paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
DATASETS_DIR = DATA_DIR / "datasets"

# GitHub file size limit is 100MB, we aim for 48MB chunks
MAX_FILE_SIZE = 48 * 1024 * 1024  # 48MB

# Add repo root to path to import ovos_localize
sys.path.insert(0, str(REPO_ROOT))

from ovos_localize.datasets import generate_intent_classification, generate_parallel_corpora


class SplitFileWriter:
    """Manages writing to split files based on size."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.chunk_index = 0
        self.current_f: Optional[TextIO] = None
        self.current_size = 0

    def _get_path(self) -> Path:
        if self.chunk_index == 0:
            return self.base_path
        return self.base_path.with_name(f"{self.base_path.stem}_{self.chunk_index}{self.base_path.suffix}")

    def write(self, data: str):
        data_bytes = data.encode("utf-8")
        if self.current_f is None:
            self.current_f = self._get_path().open("w", encoding="utf-8")
            self.current_size = 0

        if self.current_size + len(data_bytes) > MAX_FILE_SIZE:
            self.current_f.close()
            self.chunk_index += 1
            self.current_f = self._get_path().open("w", encoding="utf-8")
            self.current_size = 0

        self.current_f.write(data)
        self.current_size += len(data_bytes)

    def close(self):
        if self.current_f:
            self.current_f.close()


def main():
    """Main generation routine."""
    if not SKILLS_DIR.exists():
        print(f"Error: {SKILLS_DIR} not found. Run generate_data.py first.")
        sys.exit(1)

    cls_dir = DATASETS_DIR / "classification"
    tra_dir = DATASETS_DIR / "translation"
    cls_dir.mkdir(parents=True, exist_ok=True)
    tra_dir.mkdir(parents=True, exist_ok=True)

    cls_writers: Dict[str, SplitFileWriter] = {}
    tra_writers: Dict[str, SplitFileWriter] = {}

    def get_cls_writer(lang: str) -> SplitFileWriter:
        if lang not in cls_writers:
            cls_writers[lang] = SplitFileWriter(cls_dir / f"{lang}.jsonl")
        return cls_writers[lang]

    def get_tra_writer(pair: str) -> SplitFileWriter:
        if pair not in tra_writers:
            tra_writers[pair] = SplitFileWriter(tra_dir / f"{pair}.jsonl")
        return tra_writers[pair]

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
                    writer = get_cls_writer(lang)
                    writer.write(json.dumps(sample, ensure_ascii=False) + "\n")

            # 2. Translation (Parallel Corpora)
            for sample in generate_parallel_corpora(skill_id, skill_data):
                pair = sample.get("pair")
                if pair:
                    writer = get_tra_writer(pair)
                    writer.write(json.dumps(sample, ensure_ascii=False) + "\n")

    finally:
        for w in cls_writers.values():
            w.close()
        for w in tra_writers.values():
            w.close()

    print(f"Datasets generated successfully in {DATASETS_DIR}")

if __name__ == "__main__":
    main()
