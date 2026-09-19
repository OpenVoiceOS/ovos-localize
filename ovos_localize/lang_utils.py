"""Language code normalization using the ``langcodes`` library.

Normalizes inconsistent casing and merges equivalent tags using BCP-47
tag distance. Provides display names for the SPA frontend.
"""

from collections.abc import Iterable

import langcodes

# Explicit normalization for OVOS specific usage
# needed for skills that don't provide full lang-code
# ideally this should be fixed skill side
EXPLICIT_MAPPING = {
    "da": "da-DK",
    "cs": "cs-CZ",
    "hu": "hu-HU",
    "pl": "pl-PL",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "ca": "ca-ES",
    "de": "de-DE",
    "en": "en-US",
    "es": "es-ES",
    "fa": "fa-IR",
    "fa-FA": "fa-IR",
    "fr": "fr-FR",
    "gl": "gl-ES",
    "it": "it-IT",
    "nl": "nl-NL",
    "pt": "pt-BR",
    "eu": "eu-ES",
    "eu-EU": "eu-ES",
    "es-LM": "es-419",
    "az": "az-AZ",
    "tr": "tr-TR",
    "uk": "uk-UA",
    "lt": "lt-LT",
    "nb": "nb-NO",
    "no": "nb-NO",  # Standardizing generic 'no' to Bokmål
    "nn": "nn-NO",
    "fi": "fi-FI",
    "el": "el-GR",
    "he": "he-IL",
    "hi": "hi-IN",
    "id": "id-ID",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "ro": "ro-RO",
    "sk": "sk-SK",
    "sl": "sl-SI",
    "th": "th-TH",
    "vi": "vi-VN",
    "zh": "zh-CN",
    # Common redundancy fixes
    "en-EN": "en-US",
    "en-UK": "en-GB",
    "fr-FA": "fr-FR",
    "jp": "ja-JP",    # 'jp' is a common mistake for 'ja'
}


def normalize_lang_code(code: str) -> str:
    """Normalize a language code to canonical BCP-47 form.

    Uses an explicit mapping for common OVOS aliases, then falls back
    to ``langcodes`` for BCP-47 standardization.

    Args:
        code: Raw language code from a locale directory name.

    Returns:
        Normalized BCP-47 language tag.
    """
    # Fix casing and whitespace for lookup
    code = code.strip()
    
    # Check explicit mapping first
    if code in EXPLICIT_MAPPING:
        return EXPLICIT_MAPPING[code]
    
    # Also check case-insensitive match for the mapping
    for k, v in EXPLICIT_MAPPING.items():
        if k.lower() == code.lower():
            return v

    try:
        tag = langcodes.Language.get(code)
        return tag.to_tag()
    except langcodes.tag_parser.LanguageTagError:
        return code.lower()


def merge_equivalent_langs(
    lang_list: list[str],
    max_distance: int = 0,
    canonical_codes: Iterable[str] | None = None,
) -> dict[str, str]:
    """Build a mapping that merges equivalent language codes.

    Codes within ``max_distance`` of each other (using ``langcodes.tag_distance``)
    are merged to a single representative.

    With ``max_distance=0`` (default), only truly equivalent codes merge:
    ``da`` and ``da-DK`` (distance 0) merge, but ``sv-FI`` and ``sv-SE``
    (distance 4) stay separate.

    A code in ``canonical_codes`` always wins, because it was chosen
    deliberately.  Otherwise the more specific tag wins.  Some languages have
    no commonly-used region -- Kabyle is ``kab``, never ``kab-DZ`` -- so
    without this a single stray region-tagged directory anywhere in the corpus
    would promote an invented tag over the real one, and every subsequent
    translation would be filed under it.

    Args:
        lang_list: List of normalized language codes.
        max_distance: Maximum tag distance to consider equivalent.
        canonical_codes: Codes that were deliberately enabled and must win.

    Returns:
        Dict mapping each input code to its canonical representative.
    """
    preferred = set(canonical_codes or ())
    # Sort: deliberately enabled codes first, then more specific tags.
    sorted_codes = sorted(
        lang_list,
        key=lambda c: (0 if c in preferred else 1, 0 if "-" in c else 1, c),
    )
    canonical: dict[str, str] = {}

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


# BCP-47 primary language subtags written right-to-left. Direction is a
# property of the language, not the script, so this is keyed on the primary
# subtag and never inferred from a script subtag (e.g. Tifinagh is LTR).
_RTL_LANGS = frozenset({
    "ar",   # Arabic
    "arc",  # Aramaic
    "ckb",  # Central Kurdish (Sorani)
    "dv",   # Divehi / Maldivian
    "fa",   # Persian
    "he",   # Hebrew
    "ps",   # Pashto
    "sd",   # Sindhi
    "ug",   # Uyghur
    "ur",   # Urdu
    "yi",   # Yiddish
})


def is_rtl(code: str) -> bool:
    """Return ``True`` if a language is written right-to-left.

    Matches the BCP-47 primary language subtag only. Writing direction is a
    property of the language rather than the script, so it is never inferred
    from a script or region subtag.

    Args:
        code: A language code such as ``"fa-IR"`` or ``"ar"``.

    Returns:
        ``True`` for right-to-left languages, ``False`` otherwise.
    """
    if not code:
        return False
    primary = code.strip().lower().split("-")[0]
    return primary in _RTL_LANGS


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


# Directory names that hold the locale trees. A locale root can sit inside a
# package directory, e.g. ``ovos_date_parser/locale/fr/months.voc``.
_LOCALE_ROOTS = frozenset({"locale", "res"})


def locale_dir_from_path(file_path: str) -> str | None:
    """Return the language directory segment of a locale resource path.

    Args:
        file_path: Repository-relative path, e.g. ``locale/en-US/foo.voc``.

    Returns:
        The segment after the locale root (``"en-US"``), or ``None`` when the
        path holds no locale root or no segment after it.
    """
    parts = file_path.strip().split("/")
    for idx, seg in enumerate(parts):
        # The language directory needs a file after it; a path that stops at
        # the locale root names no language.
        if seg in _LOCALE_ROOTS and len(parts) >= idx + 3 and parts[idx + 1]:
            return parts[idx + 1]
    return None


def locale_dir_matches_lang(dir_name: str, lang: str) -> bool:
    """Tell if a locale directory name and a language tag are the same language.

    A repository writes the same language in more than one shape: Kabyle is
    ``kab`` in one tree and ``kab-DZ`` in another, and many trees drop the
    region (``locale/fr/``) for a tag that carries one (``fr-FR``). Those are
    the same language and must match. ``en-US`` against ``en-GB``, or ``fr``
    against ``kab``, are different languages and must not.

    Args:
        dir_name: The language directory segment, e.g. ``"fr"``.
        lang: The submitted language tag, e.g. ``"kab"``.

    Returns:
        ``True`` when both name the same language.
    """
    a, b = (dir_name or "").strip(), (lang or "").strip()
    if not a or not b:
        return False
    try:
        if langcodes.tag_distance(a, b) == 0:
            return True
    except (langcodes.tag_parser.LanguageTagError, LookupError):
        pass
    norm_a, norm_b = normalize_lang_code(a), normalize_lang_code(b)
    if norm_a.split("-")[0].lower() != norm_b.split("-")[0].lower():
        return False
    # Same language, different region. One side without a region is the same
    # language written less precisely, which every locale tree does; two
    # different regions are two different languages for translation purposes.
    return "-" not in a or "-" not in b


def check_path_lang(file_path: str, lang: str) -> str | None:
    """Check that a submitted file path is written in the submitted language.

    Args:
        file_path: The ``file_path`` value of a ``TRANSLATION_META`` block.
        lang: The ``lang`` value of the same block.

    Returns:
        ``None`` when the path and the language agree, else a message that
        says why they do not.
    """
    dir_name = locale_dir_from_path(file_path)
    if dir_name is None:
        return f"file_path has no language directory under locale/ or res/: {file_path}"
    if not locale_dir_matches_lang(dir_name, lang):
        return (
            f"file_path is written to the '{dir_name}' locale directory but lang is "
            f"'{lang}': {file_path}. The path must name the target language."
        )
    return None
