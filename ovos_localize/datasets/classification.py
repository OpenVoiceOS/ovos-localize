"""Dataset generator for NLU intent classification."""

from typing import Any, Dict, Iterator


def generate_intent_classification(skill_id: str, skill_data: dict) -> Iterator[Dict[str, Any]]:
    """Yield intent classification samples from a skill's parsed data.

    Extracts entries from `.intent` and `.voc` files.

    Args:
        skill_id: The ID of the skill (e.g., 'ovos-skill-hello-world').
        skill_data: The JSON dictionary representation of the parsed skill.

    Yields:
        Dictionaries containing text, intent, lang, and skill metadata.
    """
    files = skill_data.get("files", {})
    for filename, file_info in files.items():
        file_type = file_info.get("type")
        if file_type not in ("intent", "voc"):
            continue

        langs = file_info.get("langs", {})
        for lang, lang_data in langs.items():
            entries = lang_data.get("entries", [])
            for entry in entries:
                text = entry.get("text", "").strip()
                if not text:
                    continue

                yield {
                    "lang": lang,
                    "skill": skill_id,
                    "file_type": file_type,
                    "intent": filename,
                    "text": text
                }
