"""Language code normalization using the ``langcodes`` library.

Normalizes inconsistent casing and merges equivalent tags using BCP-47
tag distance. Provides display names for the SPA frontend.
"""

import json
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


def canonical_lang_spelling(tag: str) -> str:
    """Return a language tag in its canonical BCP-47 spelling.

    Casing only: no alias is expanded, so ``pt`` stays ``pt`` rather than
    becoming ``pt-BR``. A script subtag is written in title case
    (``zh-HANT`` becomes ``zh-Hant``) and a region in upper case
    (``kab-dz`` becomes ``kab-DZ``).

    Args:
        tag: A language tag or locale directory name.

    Returns:
        The canonical spelling, or the input when it cannot be parsed.
    """
    try:
        return langcodes.Language.get(tag.strip()).to_tag()
    except (langcodes.tag_parser.LanguageTagError, LookupError, ValueError):
        return tag.strip()


def load_supported_langs(path: str) -> list[str]:
    """Read the project's supported language tags from a coverage file.

    Args:
        path: Path to ``data/coverage.json``.

    Returns:
        The tags under the ``languages`` key.
    """
    with open(path, encoding="utf-8") as handle:
        return list(json.load(handle).get("languages") or [])


def _primary(tag: str) -> str:
    return canonical_lang_spelling(tag).split("-")[0].lower()


def regional_siblings(lang: str, supported: Iterable[str]) -> list[str]:
    """Return the supported tags that are another region of ``lang``.

    ``pt-BR`` has ``pt-PT`` and ``pt-AO``. ``kab-DZ`` has none, because the
    only supported Kabyle tag is the region-less ``kab``, which is the same
    language written less precisely rather than another region.

    Args:
        lang: The language tag being written.
        supported: Every tag the project supports.

    Returns:
        The other regional tags of the same language, sorted.
    """
    primary = _primary(lang)
    return sorted(
        tag for tag in supported
        if "-" in tag and _primary(tag) == primary
        and canonical_lang_spelling(tag) != canonical_lang_spelling(lang)
    )


def locale_dir_matches_lang(dir_name: str, lang: str, supported: Iterable[str] | None = None) -> bool:
    """Tell if a locale directory name and a language tag are the same language.

    A repository writes the same language in more than one shape: Kabyle is
    ``kab`` in one tree and ``kab-DZ`` in another, and many trees drop the
    region (``locale/fr/``) for a tag that carries one (``fr-FR``). Those are
    the same language and match. ``en-US`` against ``en-GB``, or ``fr``
    against ``kab``, are different languages and do not.

    A region-less directory is the same language ONLY while the project
    supports one region of it. ``ovos-date-parser`` ships ``locale/pt/``, and
    ``pt-BR``, ``pt-PT`` and ``pt-AO`` are all supported, so that directory
    names no single one of them and a regional tag written into it would
    overwrite another region's file. ``supported`` is what decides this, and
    without it every regional tag against a region-less directory is refused,
    because the question cannot be answered.

    Args:
        dir_name: The language directory segment, e.g. ``"fr"``.
        lang: The submitted language tag, e.g. ``"kab"``.
        supported: Every tag the project supports, or ``None``.

    Returns:
        ``True`` when both name the same language and the directory names it
        without ambiguity.
    """
    a, b = (dir_name or "").strip(), (lang or "").strip()
    if not a or not b:
        return False
    # The directory must be spelled the way this project spells a tag. A
    # lower-case directory is the legacy spelling that many repositories
    # already ship (en-us, pt-br, kab-dz); anything else, zh-HANT included,
    # is a directory the rest of the code would not name.
    canonical_dir = canonical_lang_spelling(a)
    if a not in (canonical_dir, canonical_dir.lower()):
        return False
    if _primary(a) != _primary(b):
        return False
    same_shape = canonical_dir.lower() == canonical_lang_spelling(b).lower()
    if same_shape:
        return True
    # From here the two differ by a region. Two named regions are two
    # languages for translation.
    if "-" in a and "-" in b:
        return False
    if "-" in a:
        # A named directory, a region-less tag: the directory decides.
        return True
    # A region-less directory and a regional tag. Two things must hold: no
    # other region of this language is supported, and this region is the one
    # the bare tag already means. kab-DZ is what kab means, so locale/kab
    # takes it; sw-KE is not what sw means, so locale/sw does not.
    if supported is None:
        return False
    if regional_siblings(b, supported):
        return False
    try:
        return langcodes.tag_distance(a, b) == 0
    except (langcodes.tag_parser.LanguageTagError, LookupError):
        return False


def check_path_lang(file_path: str, lang: str, supported: Iterable[str] | None = None) -> str | None:
    """Check that a submitted file path is written in the submitted language.

    Args:
        file_path: The ``file_path`` value of a ``TRANSLATION_META`` block.
        lang: The ``lang`` value of the same block.
        supported: Every tag the project supports, or ``None``.

    Returns:
        ``None`` when the path and the language agree, else a message that
        says why they do not.
    """
    dir_name = locale_dir_from_path(file_path)
    if dir_name is None:
        return f"file_path has no language directory under locale/ or res/: {file_path}"
    canonical_dir = canonical_lang_spelling(dir_name)
    if dir_name not in (canonical_dir, canonical_dir.lower()):
        return (
            f"the locale directory '{dir_name}' is not spelled the way this project "
            f"spells a language tag; write '{canonical_dir}': {file_path}"
        )
    if "-" not in dir_name and "-" in lang and not locale_dir_matches_lang(dir_name, lang, supported):
        siblings = regional_siblings(lang, supported or ())
        if supported is None or siblings or _primary(dir_name) == _primary(lang):
            named = ", ".join(siblings) or f"another region of {_primary(lang)}"
            return (
                f"'{dir_name}' is a region-less locale directory and '{lang}' names a "
                f"region. {named} would be written to the same file: {file_path}. "
                f"Write the full tag as the directory."
            )
    if not locale_dir_matches_lang(dir_name, lang, supported):
        return (
            f"file_path is written to the '{dir_name}' locale directory but lang is "
            f"'{lang}': {file_path}. The path must name the target language."
        )
    return None
