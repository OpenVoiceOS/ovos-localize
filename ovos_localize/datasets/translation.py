"""Dataset generator for parallel corpora (machine translation)."""

from typing import Any, Dict, Iterator


def generate_parallel_corpora(skill_id: str, skill_data: dict, base_lang: str = "en-US") -> Iterator[Dict[str, Any]]:
    """Yield parallel translations from a skill's parsed data.

    Pairs the base language (default en-US) with other languages found in the same file.
    
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
        
        # We need the base language to exist in this file to pair it
        if base_lang not in langs:
            # Fallback: check if any 'en-*' exists if 'en-US' is requested and missing
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

        base_data = langs[base_lang_key]
        base_texts = [
            e.get("text").strip() 
            for e in base_data.get("entries", []) 
            if e.get("text", "").strip()
        ]
        
        if not base_texts:
            continue

        file_type = file_info.get("type", "unknown")

        for target_lang, target_data in langs.items():
            if target_lang == base_lang_key:
                continue

            target_texts = [
                e.get("text").strip() 
                for e in target_data.get("entries", []) 
                if e.get("text", "").strip()
            ]
            
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
