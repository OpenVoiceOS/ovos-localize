"""Dataset generator for parallel corpora (machine translation)."""

from collections.abc import Iterator
from typing import Any

from ovos_localize.bracket_expansion import clean_text, expand_template


def generate_parallel_corpora(skill_id: str, skill_data: dict, base_lang: str = "en-US") -> Iterator[dict[str, Any]]:
    """Yield parallel translations from a skill's parsed data.

    Pairs the base language (default en-US) with other languages found in the same file.
    Expands templates, lowercases, and deduplicates pairs.

    Args:
        skill_id: The ID of the skill (e.g., 'ovos-skill-hello-world').
        skill_data: The JSON dictionary representation of the parsed skill.
        base_lang: The language code to pivot on.

    Yields:
        Dictionaries containing base_texts, target_texts, and metadata.
    """
    files = skill_data.get("files", {})
    for filename, file_info in files.items():
        langs = file_info.get("langs", {})

        # Pivot language check
        if base_lang not in langs:
            if base_lang == "en-US":
                alt_en = [l for l in langs.keys() if l.lower().startswith("en-")]
                if alt_en:
                    base_lang_key = alt_en[0]
                else:
                    continue
            else:
                continue
        else:
            base_lang_key = base_lang

        def _get_cleaned_entries(lang_key: str) -> set[str]:
            seen = set()
            for entry in langs[lang_key].get("entries", []):
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue
                for expanded in expand_template(template):
                    cleaned = clean_text(expanded)
                    if cleaned:
                        seen.add(cleaned)
            return seen

        base_texts = sorted(list(_get_cleaned_entries(base_lang_key)))
        if not base_texts:
            continue

        file_type = file_info.get("type", "unknown")

        for target_lang, target_data in langs.items():
            if target_lang == base_lang_key:
                continue

            target_texts = sorted(list(_get_cleaned_entries(target_lang)))
            if not target_texts:
                continue

            yield {
                "pair": f"{base_lang_key}_{target_lang}",
                "base_lang": base_lang_key,
                "target_lang": target_lang,
                "skill": skill_id,
                "file_type": file_type,
                "file_name": filename,
                "base_texts": base_texts,
                "target_texts": target_texts
            }
