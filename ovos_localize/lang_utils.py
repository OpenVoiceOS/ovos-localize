"""Language code normalization using the ``langcodes`` library.

Normalizes inconsistent casing and merges equivalent tags using BCP-47
tag distance. Provides display names for the SPA frontend.
"""

from typing import Dict, List, Tuple

import langcodes


def normalize_lang_code(code: str) -> str:
    """Normalize a language code to canonical BCP-47 form.

    Uses ``langcodes`` for proper BCP-47 standardization:
    - Fixes casing: ``en-us`` → ``en-US``, ``fa-ir`` → ``fa-IR``
    - Bare codes stay bare if no default region is unambiguous:
      ``da`` stays ``da``, ``en-us`` stays ``en-US``

    Args:
        code: Raw language code from a locale directory name.

    Returns:
        Normalized BCP-47 language tag.
    """
    try:
        tag = langcodes.Language.get(code)
        return tag.to_tag()
    except langcodes.tag_parser.LanguageTagError:
        return code.strip().lower()


def merge_equivalent_langs(lang_list: List[str], max_distance: int = 0) -> Dict[str, str]:
    """Build a mapping that merges equivalent language codes.

    Codes within ``max_distance`` of each other (using ``langcodes.tag_distance``)
    are merged to the more specific tag (the one with a region subtag).

    With ``max_distance=0`` (default), only truly equivalent codes merge:
    ``da`` and ``da-DK`` (distance 0) merge, but ``sv-FI`` and ``sv-SE``
    (distance 4) stay separate.

    Args:
        lang_list: List of normalized language codes.
        max_distance: Maximum tag distance to consider equivalent.

    Returns:
        Dict mapping each input code to its canonical representative.
    """
    # Sort: codes with region subtags first (more specific = better canonical form)
    sorted_codes = sorted(lang_list, key=lambda c: (0 if "-" in c else 1, c))
    canonical: Dict[str, str] = {}

    for code in sorted_codes:
        # Check if this code is equivalent to an already-seen canonical
        merged = False
        for canon in canonical.values():
            if canon == code:
                continue
            dist = langcodes.tag_distance(code, canon)
            if dist <= max_distance:
                canonical[code] = canon
                merged = True
                break
        if not merged:
            canonical[code] = code

    return canonical


def lang_display_name(code: str) -> str:
    """Get a human-readable display name for a language code.

    Args:
        code: BCP-47 language tag.

    Returns:
        Display name string, e.g. ``"German (Germany)"`` for ``de-DE``.
    """
    try:
        return langcodes.Language.get(code).display_name()
    except langcodes.tag_parser.LanguageTagError:
        return code


def lang_display_name_native(code: str) -> str:
    """Get the autonym (self-name) for a language code.

    Args:
        code: BCP-47 language tag.

    Returns:
        Native name string, e.g. ``"Deutsch"`` for ``de-DE``.
    """
    try:
        lang = langcodes.Language.get(code)
        return lang.display_name(language=lang)
    except (langcodes.tag_parser.LanguageTagError, Exception):
        return code
