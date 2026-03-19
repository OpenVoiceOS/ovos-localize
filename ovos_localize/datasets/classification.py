"""Dataset generator for NLU intent classification."""

from typing import Any, Dict, Iterator, Set
from ovos_localize.bracket_expansion import expand_template, clean_text


def generate_intent_classification(skill_id: str, skill_data: dict) -> Iterator[Dict[str, Any]]:
    """Yield intent classification samples from a skill's parsed data.

    Expands templates, lowercases, and deduplicates phrases.

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
            seen: Set[str] = set()
            entries = lang_data.get("entries", [])
            for entry in entries:
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue

                # Expand templates: "(hello|hi) world" -> "hello world", "hi world"
                for expanded in expand_template(template):
                    cleaned = clean_text(expanded)
                    if not cleaned or cleaned in seen:
                        continue
                    seen.add(cleaned)

                    yield {
                        "lang": lang,
                        "skill": skill_id,
                        "file_type": file_type,
                        "intent": filename,
                        "text": cleaned
                    }
