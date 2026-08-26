"""Dataset generator for multilingual skill metadata.

Exports ``skill.json`` file content (name, description, example utterances,
tags) per language.  Useful as a zero-shot classification baseline, skill
discovery corpus, or multilingual short-text benchmark.
"""

from collections.abc import Iterator
from typing import Any

_TRANSLATABLE_KEYS = ("name", "description", "examples")


def generate_skill_metadata(skill_id: str, skill_data: dict) -> Iterator[dict[str, Any]]:
    """Yield skill metadata records from ``skill.json`` locale files.

    Only emits records that have at least a ``name`` and ``description`` in
    the target language.  The ``examples`` field (example voice commands) is
    included when present.

    Args:
        skill_id: Skill identifier (e.g. ``'ovos-skill-hello-world'``).
        skill_data: Parsed skill JSON dictionary.

    Yields:
        Dicts with keys ``lang``, ``skill``, ``name``, ``description``,
        ``examples`` (list of strings), and ``tags`` (list of strings).
    """
    files = skill_data.get("files", {})
    for filename, file_info in files.items():
        if file_info.get("type") != "skill.json":
            continue

        for lang, lang_data in file_info.get("langs", {}).items():
            # Build a flat key→value dict from entries
            kv: dict[str, str] = {}
            for entry in lang_data.get("entries", []):
                key = entry.get("key", "")
                text = entry.get("text", "").strip()
                if key and text:
                    kv[key] = text

            name = kv.get("name", "").strip()
            description = kv.get("description", "").strip()
            if not name or not description:
                continue

            raw_examples = kv.get("examples", "")
            examples = [e.strip() for e in raw_examples.split("\n") if e.strip()] if raw_examples else []

            raw_tags = kv.get("tags", "")
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()] if raw_tags else []

            yield {
                "lang": lang,
                "skill": skill_id,
                "name": name,
                "description": description,
                "examples": examples,
                "tags": tags,
            }
