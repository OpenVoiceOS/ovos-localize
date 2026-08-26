#!/usr/bin/env python3
"""Generate ML datasets from parsed OVOS skill JSON files.

Reads from ``data/skills/`` and outputs JSONL datasets to ``data/datasets/``.

Datasets generated
------------------
classification/
    One JSONL per language: intent/voc utterances with skill+intent label.
translation/
    One JSONL per language pair: parallel corpora for machine translation.
slot_filling/
    One JSONL per language: intent templates with slot names + known entity values.
response_pairs/
    One JSONL per language: (utterance, responses) pairs via AST handler analysis.
tts/
    One JSONL per language: deduplicated dialog sentences for TTS training.
skill_metadata/
    One JSONL per language: skill name, description, examples, tags.
"""

import json
import sys
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SKILLS_DIR = DATA_DIR / "skills"
DATASETS_DIR = DATA_DIR / "datasets"

MAX_FILE_SIZE = 48 * 1024 * 1024  # 48 MB — stay under GitHub's 100 MB limit

sys.path.insert(0, str(REPO_ROOT))

from ovos_localize.datasets import (
    generate_intent_classification,
    generate_parallel_corpora,
    generate_response_pairs,
    generate_skill_metadata,
    generate_slot_filling,
    generate_tts_corpus,
)


class SplitFileWriter:
    """Writes JSONL to one or more chunked files capped at *MAX_FILE_SIZE*."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.chunk_index = 0
        self.current_f: TextIO | None = None
        self.current_size = 0

    def _get_path(self) -> Path:
        if self.chunk_index == 0:
            return self.base_path
        return self.base_path.with_name(
            f"{self.base_path.stem}_{self.chunk_index}{self.base_path.suffix}"
        )

    def write(self, data: str) -> None:
        """Write *data* to the current chunk, rolling over when the size limit is reached."""
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

    def close(self) -> None:
        """Flush and close the current chunk file."""
        if self.current_f:
            self.current_f.close()


WriterPool = dict[str, SplitFileWriter]


def _get_writer(pool: WriterPool, key: str, directory: Path, suffix: str = ".jsonl") -> SplitFileWriter:
    if key not in pool:
        pool[key] = SplitFileWriter(directory / f"{key}{suffix}")
    return pool[key]


def _close_all(pool: WriterPool) -> None:
    for w in pool.values():
        w.close()


def main() -> None:
    """Run the full dataset generation pipeline."""
    if not SKILLS_DIR.exists():
        print(f"Error: {SKILLS_DIR} not found. Run generate_data.py first.")
        sys.exit(1)

    cls_dir = DATASETS_DIR / "classification"
    tra_dir = DATASETS_DIR / "translation"
    sf_dir = DATASETS_DIR / "slot_filling"
    rp_dir = DATASETS_DIR / "response_pairs"
    tts_dir = DATASETS_DIR / "tts"
    meta_dir = DATASETS_DIR / "skill_metadata"

    for d in (cls_dir, tra_dir, sf_dir, rp_dir, tts_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    cls_writers: WriterPool = {}
    tra_writers: WriterPool = {}
    sf_writers: WriterPool = {}
    rp_writers: WriterPool = {}
    tts_writers: WriterPool = {}
    meta_writers: WriterPool = {}

    try:
        for skill_file in sorted(SKILLS_DIR.glob("*.json")):
            skill_id = skill_file.stem
            try:
                with open(skill_file, encoding="utf-8") as f:
                    skill_data = json.load(f)
            except Exception as e:
                print(f"Failed to load {skill_file}: {e}", file=sys.stderr)
                continue

            # 1. Intent classification
            for sample in generate_intent_classification(skill_id, skill_data):
                if lang := sample.get("lang"):
                    _get_writer(cls_writers, lang, cls_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

            # 2. Parallel corpora (machine translation)
            for sample in generate_parallel_corpora(skill_id, skill_data):
                if pair := sample.get("pair"):
                    _get_writer(tra_writers, pair, tra_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

            # 3. Slot filling / NER
            for sample in generate_slot_filling(skill_id, skill_data):
                if lang := sample.get("lang"):
                    _get_writer(sf_writers, lang, sf_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

            # 4. Intent → dialog response pairs (AST-derived)
            for sample in generate_response_pairs(skill_id, skill_data):
                if lang := sample.get("lang"):
                    _get_writer(rp_writers, lang, rp_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

            # 5. TTS corpus (dialog sentences)
            for sample in generate_tts_corpus(skill_id, skill_data):
                if lang := sample.get("lang"):
                    _get_writer(tts_writers, lang, tts_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

            # 6. Skill metadata
            for sample in generate_skill_metadata(skill_id, skill_data):
                if lang := sample.get("lang"):
                    _get_writer(meta_writers, lang, meta_dir).write(
                        json.dumps(sample, ensure_ascii=False) + "\n"
                    )

    finally:
        for pool in (cls_writers, tra_writers, sf_writers, rp_writers, tts_writers, meta_writers):
            _close_all(pool)

    # Write index.json: which files actually exist per dataset type
    index: dict = {}
    for type_dir in (cls_dir, tra_dir, sf_dir, rp_dir, tts_dir, meta_dir):
        key = type_dir.name
        index[key] = sorted(p.name for p in type_dir.glob("*.jsonl"))
    index_path = DATASETS_DIR / "index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))

    print(f"Datasets generated successfully in {DATASETS_DIR}")


if __name__ == "__main__":
    main()
