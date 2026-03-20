"""Dataset generator for slot-filling / NER training data.

Each record pairs an utterance template with its slot names and any known
entity values from the corresponding .entity file.
"""

import re
from typing import Any, Dict, Iterator, List, Set

from ovos_localize.bracket_expansion import expand_template, clean_text

_SLOT_RE = re.compile(r"\{(\w+)\}")


def _slot_names(text: str) -> List[str]:
    """Return all slot names found in *text*."""
    return _SLOT_RE.findall(text)


def generate_slot_filling(skill_id: str, skill_data: dict) -> Iterator[Dict[str, Any]]:
    """Yield slot-filling samples from a skill's parsed intent and entity data.

    For each intent utterance that contains ``{slot}`` placeholders, emits a
    record with the raw template, all slot names, and — where a matching
    ``.entity`` file exists — the known entity values for each slot.

    Args:
        skill_id: Skill identifier (e.g. ``'ovos-skill-application-launcher'``).
        skill_data: Parsed skill JSON dictionary.

    Yields:
        Dicts with keys ``lang``, ``skill``, ``intent``, ``template``,
        ``slots``, and ``entity_values`` (``{slot_name: [value, ...]}``)
    """
    files = skill_data.get("files", {})

    # Build entity value lookup: slot_name → lang → [values]
    entity_values: Dict[str, Dict[str, List[str]]] = {}
    for filename, file_info in files.items():
        if file_info.get("type") != "entity":
            continue
        slot_name = filename.replace(".entity", "")
        entity_values[slot_name] = {}
        for lang, lang_data in file_info.get("langs", {}).items():
            vals = [
                e["text"]
                for e in lang_data.get("entries", [])
                if e.get("text", "").strip() and not e["text"].startswith("#")
            ]
            if vals:
                entity_values[slot_name][lang] = vals

    for filename, file_info in files.items():
        if file_info.get("type") not in ("intent",):
            continue

        seen: Set[str] = set()
        for lang, lang_data in file_info.get("langs", {}).items():
            for entry in lang_data.get("entries", []):
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue
                slots = _slot_names(template)
                if not slots:
                    continue

                key = f"{lang}:{template}"
                if key in seen:
                    continue
                seen.add(key)

                ev: Dict[str, List[str]] = {
                    s: entity_values.get(s, {}).get(lang, []) for s in slots
                }

                yield {
                    "lang": lang,
                    "skill": skill_id,
                    "intent": filename,
                    "template": template,
                    "slots": slots,
                    "entity_values": ev,
                }
