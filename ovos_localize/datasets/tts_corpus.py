"""Dataset generator for TTS (Text-to-Speech) training corpora.

Exports all dialog file entries — the spoken responses of OVOS skills — as a
clean, deduplicated text corpus per language.  Dialog lines are natural
spoken-language sentences and are the largest file type in the corpus
(~1 500 files across 26 languages).
"""

from collections.abc import Iterator
from typing import Any

from ovos_localize.bracket_expansion import clean_text, expand_template


def generate_tts_corpus(skill_id: str, skill_data: dict) -> Iterator[dict[str, Any]]:
    """Yield TTS corpus samples from a skill's dialog files.

    Expands ``(a|b)`` / ``[optional]`` templates so every unique surface form
    is emitted as a separate record.  Skips comment lines and deduplicates
    within each language.

    Args:
        skill_id: Skill identifier (e.g. ``'ovos-skill-hello-world'``).
        skill_data: Parsed skill JSON dictionary.

    Yields:
        Dicts with keys ``lang``, ``skill``, ``dialog`` (source filename),
        and ``text`` (a single spoken utterance).
    """
    files = skill_data.get("files", {})
    for filename, file_info in files.items():
        if file_info.get("type") != "dialog":
            continue

        seen: set[str] = set()
        for lang, lang_data in file_info.get("langs", {}).items():
            for entry in lang_data.get("entries", []):
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue

                for expanded in expand_template(template):
                    text = clean_text(expanded)
                    if not text:
                        continue
                    key = f"{lang}:{text}"
                    if key in seen:
                        continue
                    seen.add(key)

                    yield {
                        "lang": lang,
                        "skill": skill_id,
                        "dialog": filename,
                        "text": text,
                    }
