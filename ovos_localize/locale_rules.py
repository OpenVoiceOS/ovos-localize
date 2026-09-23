"""One rule for where a translation is written, for both halves of the platform.

The page composes the path of a new file and the submission workflow checks
it. Two implementations of one rule agree only by luck, and they have
already drifted once: the page upper-cased every subtag after the first,
which is right for a region and wrong for a script or a variant, and it
counted a region-less tag as a rival region where the check did not.

So the rule lives here, in Python, and the page reads the answer. This
module turns the project's language list into a table, one entry per tag:

``canonical``
    The spelling of the tag, from ``langcodes``. ``zh-HANT`` is written
    ``zh-Hant``, ``kab-dz`` is written ``kab-DZ``, and a variant subtag
    stays lower case: ``ca-ES-valencia``.
``primary``
    The primary subtag, which is the directory name of a region-less tree.
``bare_ok``
    Whether this tag may be written into a region-less directory of its own
    language. ``kab-DZ`` may, because Kabyle has no other supported region
    and ``kab`` already means it. ``pt-BR`` may not, because ``pt-PT`` would
    be written to the same file, and ``sw-KE`` may not, because the bare
    ``sw`` tag does not mean Kenya.
``rivals``
    The tags that would take that same region-less directory. They are named
    to the translator.

``scripts/gen_locale_rules.py`` writes the table to ``data/locale_rules.json``
and ``test_locale_rules.py`` fails when the committed file no longer matches
what this module builds, so the page can never read a stale rule.
"""

import json
from collections.abc import Iterable

import langcodes

from ovos_localize.lang_utils import canonical_lang_spelling

# Directory names that hold the locale trees. A locale root can sit inside a
# package directory, e.g. ``ovos_date_parser/locale/fr/months.voc``.
LOCALE_ROOTS = frozenset({"locale", "res"})

# Why a path was refused. Both halves answer with one of these, so a test can
# compare them by more than a boolean.
OK = "ok"
NO_LOCALE_ROOT = "no-locale-root"
UNKNOWN_TAG = "unknown-tag"
REGION_COLLISION = "region-collision"
BAD_SPELLING = "bad-spelling"
DIFFERENT_LANGUAGE = "different-language"

# Every field of a tag entry that a reader of the table uses. A table missing
# one of them is not usable, whatever else it holds.
TAG_FIELDS = ("canonical", "primary", "bare_ok", "rivals")


def _primary(tag: str) -> str:
    return canonical_lang_spelling(tag).split("-")[0].lower()


def _same_language(one: str, other: str) -> bool:
    """Tell if two tags name the same language for translation purposes."""
    try:
        return langcodes.tag_distance(one, other) == 0
    except (langcodes.tag_parser.LanguageTagError, LookupError):
        return False


def _bare_means(tag: str) -> bool:
    """Tell if the region-less form of ``tag`` already means ``tag``.

    ``kab`` means ``kab-DZ`` and ``fr`` means ``fr-FR``; ``sw`` does not mean
    ``sw-KE``. ``langcodes`` answers this from CLDR's default region.
    """
    try:
        return langcodes.tag_distance(_primary(tag), tag) == 0
    except (langcodes.tag_parser.LanguageTagError, LookupError):
        return False


def build_locale_rules(tags: Iterable[str]) -> dict:
    """Build the table both halves read.

    A rival is another language that would take the same region-less
    directory. The bare tag of the language is not a rival of its own
    regional tag when the two mean the same thing: ``kab`` means ``kab-DZ``
    and ``fr`` means ``fr-FR``, so those regional tags may take
    ``locale/kab`` and ``locale/fr``. ``sw`` does not mean ``sw-KE``, and
    ``ca`` is not ``ca-ES-valencia`` beside ``ca-ES``, so those may not.

    Args:
        tags: Every language tag the platform may be asked to write, in any
            spelling.

    Returns:
        ``{"tags": {<lower-case spelling>: {canonical, primary, bare_ok,
        rivals}}}``. Every spelling of one tag points at one entry.
    """
    spellings = [tag.strip() for tag in tags if tag and tag.strip()]
    canonical_set = sorted({canonical_lang_spelling(tag) for tag in spellings})

    entries = {}
    for canonical in canonical_set:
        primary = _primary(canonical)
        rivals = []
        for other in canonical_set:
            if other == canonical or _primary(other) != primary:
                continue
            # The bare tag of the language is the directory itself, not a
            # rival for it, while the two mean the same thing.
            if "-" not in other and _same_language(other, canonical):
                continue
            rivals.append(other)
        if "-" not in canonical:
            bare_ok = True
        else:
            bare_ok = not rivals and _bare_means(canonical)
        entries[canonical] = {
            "canonical": canonical,
            "primary": primary,
            "bare_ok": bare_ok,
            "rivals": sorted(rivals),
        }

    table = {}
    for tag in spellings:
        table[tag.lower()] = entries[canonical_lang_spelling(tag)]
    return {"tags": table}


def load_locale_rules(path: str) -> dict:
    """Read the generated table.

    Args:
        path: Path to ``data/locale_rules.json``.

    Returns:
        The table, in the shape ``build_locale_rules`` returns.

    Raises:
        OSError: The file is missing or unreadable.
        ValueError: The file is not the table, holds no tags, or holds an
            entry that is missing a field.
    """
    with open(path, encoding="utf-8") as handle:
        rules = json.load(handle)
    if not isinstance(rules, dict) or not isinstance(rules.get("tags"), dict):
        raise ValueError(f"{path} is not a locale-rules table")
    # An empty or half-written table answers UNKNOWN_TAG for every tag there
    # is. The caller cannot tell that from a translator who wrote a real
    # unknown tag, so the workflow would label a correct submission
    # invalid-file-path and refuse it for a fault of our own. A broken table
    # is a setup error, and it is read as one here, once, before any answer
    # is given.
    if not rules["tags"]:
        raise ValueError(f"{path} holds no tags")
    for spelling, entry in rules["tags"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: entry for {spelling!r} is not an object")
        missing = [field for field in TAG_FIELDS if field not in entry]
        if missing:
            raise ValueError(
                f"{path}: entry for {spelling!r} is missing {', '.join(missing)}")
    return rules


def locale_root_index(parts: list) -> int:
    """Return the index of the locale root whose next segment is the language.

    A tree nests the two roots: ovos-plugin-common-play ships
    ``ovos_plugin_common_play/ocp/res/locale/en-us/Music.voc``, 699 paths of
    that shape in the manifests. Taking the first root reads ``locale`` as
    the language, which refuses a correct submission and makes the page
    compose a path into a directory called ``locale``. So the root that
    counts is the innermost one: the last whose own next segment is not
    another root.

    Args:
        parts: The path, already split on ``/``.

    Returns:
        The index of the locale root, or ``-1`` when the path holds none.
    """
    for idx in range(len(parts) - 1, -1, -1):
        if (parts[idx] in LOCALE_ROOTS and len(parts) >= idx + 3
                and parts[idx + 1] and parts[idx + 1] not in LOCALE_ROOTS):
            return idx
    return -1


def locale_dir_from_path(file_path: str) -> str | None:
    """Return the language directory segment of a locale resource path.

    Args:
        file_path: Repository-relative path, e.g. ``locale/en-US/foo.voc``.

    Returns:
        The segment after the locale root, or ``None`` when there is none.
    """
    parts = file_path.strip().split("/")
    idx = locale_root_index(parts)
    return parts[idx + 1] if idx != -1 else None


def _locale_root_index(parts: list) -> int:
    return locale_root_index(parts)


def compose_locale_path(ref_path: str, target_lang: str, rules: dict,
                        file_key: str | None = None) -> dict:
    """Place a resource file for a target language, from a reference path.

    This is the rule the page runs. It is written here as well so that a test
    can run both over the same inputs and compare the answer and the reason.

    Args:
        ref_path: Path of the reference file the translator reads.
        target_lang: The language being translated into.
        rules: The table from ``build_locale_rules``.
        file_key: Resource name, when the reference is another file.

    Returns:
        ``{"path": str, "reason": str, "rivals": list}``. The path is empty
        whenever the reason is not ``ok``.
    """
    refused = {"path": "", "reason": NO_LOCALE_ROOT, "rivals": []}
    if not ref_path or not target_lang:
        return refused
    parts = str(ref_path).split("/")
    idx = _locale_root_index(parts)
    if idx == -1:
        return refused
    rule = (rules.get("tags") or {}).get(str(target_lang).strip().lower())
    if rule is None:
        return {"path": "", "reason": UNKNOWN_TAG, "rivals": []}
    ref_seg = parts[idx + 1]
    if "-" in ref_seg:
        seg = rule["canonical"]
    else:
        if not rule["bare_ok"]:
            return {"path": "", "reason": REGION_COLLISION, "rivals": rule["rivals"]}
        seg = rule["primary"]
    if ref_seg == ref_seg.lower():
        seg = seg.lower()
    if file_key:
        path = "/".join(parts[:idx + 1] + [seg, file_key])
    else:
        path = "/".join(parts[:idx + 1] + [seg] + parts[idx + 2:])
    return {"path": path, "reason": OK, "rivals": rule["rivals"]}


def check_path_lang(file_path: str, lang: str, rules: dict) -> tuple:
    """Check that a submitted path is written in the submitted language.

    The same table answers here, so the page cannot compose a path this
    refuses.

    Args:
        file_path: The ``file_path`` of a ``TRANSLATION_META`` block.
        lang: The ``lang`` of the same block.
        rules: The table from ``build_locale_rules``.

    Returns:
        ``(reason, message)``. The reason is ``ok`` and the message empty
        when the path is right.
    """
    dir_name = locale_dir_from_path(file_path)
    if dir_name is None:
        return NO_LOCALE_ROOT, (
            f"file_path has no language directory under locale/ or res/: {file_path}")
    rule = (rules.get("tags") or {}).get(str(lang).strip().lower())
    if rule is None:
        return UNKNOWN_TAG, (
            f"'{lang}' is not a language this project writes. Add it to the "
            f"enabled languages first: {file_path}")
    canonical_dir = canonical_lang_spelling(dir_name)
    # A lower-case directory is the legacy spelling that many repositories
    # already ship (en-us, pt-br, kab-dz). Anything else is a directory the
    # rest of the code would not name.
    if dir_name not in (canonical_dir, canonical_dir.lower()):
        return BAD_SPELLING, (
            f"the locale directory '{dir_name}' is not spelled the way this project "
            f"spells a language tag; write '{canonical_dir}': {file_path}")
    if _primary(dir_name) != rule["primary"]:
        return DIFFERENT_LANGUAGE, (
            f"file_path is written to the '{dir_name}' locale directory but lang is "
            f"'{lang}': {file_path}. The path must name the target language.")
    if canonical_dir.lower() == rule["canonical"].lower():
        return OK, ""
    if "-" not in dir_name:
        if rule["bare_ok"]:
            return OK, ""
        named = ", ".join(rule["rivals"]) or f"another region of {rule['primary']}"
        return REGION_COLLISION, (
            f"'{dir_name}' is a region-less locale directory and '{lang}' names a "
            f"region. {named} would be written to the same file: {file_path}. "
            f"Write the full tag as the directory.")
    if "-" not in rule["canonical"]:
        # A named directory and a region-less tag. This is the mirror of the
        # collision above and it overwrites just as much: a submission that
        # says lang: pt into locale/pt-PT writes generic Portuguese over the
        # European Portuguese file. The page never composes such a path, but
        # a TRANSLATION_META block is written by whoever opens the issue, so
        # the guard is the only barrier.
        #
        # It is allowed only where the two already mean the same thing: the
        # directory's own tag may take the region-less directory of its
        # language (bare_ok), which is true of kab-DZ and fr-FR and false of
        # pt-PT, es-ES, sv-SE, sw-KE, sr-Latn and ca-ES-valencia.
        dir_rule = (rules.get("tags") or {}).get(canonical_dir.lower())
        if dir_rule and dir_rule["bare_ok"]:
            return OK, ""
        named = ", ".join((dir_rule or {}).get("rivals") or ()) or "another region"
        return REGION_COLLISION, (
            f"'{lang}' names no region and '{dir_name}' does, and {named} is written "
            f"separately: {file_path}. Write the full tag as the language."
        )
    return DIFFERENT_LANGUAGE, (
        f"file_path is written to the '{dir_name}' locale directory but lang is "
        f"'{lang}': {file_path}. The path must name the target language.")
