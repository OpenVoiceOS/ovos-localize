"""OVOS locale file parsers — one per file type."""

from ovos_localize.parsers.base import ParsedFile, ParsedLine
from ovos_localize.parsers.intent import IntentParser
from ovos_localize.parsers.vocab import VocabParser
from ovos_localize.parsers.dialog import DialogParser
from ovos_localize.parsers.entity import EntityParser
from ovos_localize.parsers.regex import RegexParser
from ovos_localize.parsers.value import ValueParser
from ovos_localize.parsers.skill_json import SkillJsonParser
from ovos_localize.parsers.settings_meta import SettingsMetaParser

PARSERS = {
    ".intent": IntentParser,
    ".voc": VocabParser,
    ".dialog": DialogParser,
    ".entity": EntityParser,
    ".rx": RegexParser,
    ".value": ValueParser,
    "skill.json": SkillJsonParser,
    "settingsmeta.json": SettingsMetaParser,
    "settingsmeta.yml": SettingsMetaParser,
    "settingsmeta.yaml": SettingsMetaParser,
}


def get_parser(filename: str) -> type:
    """Return the appropriate parser class for a given filename.

    Args:
        filename: The filename or basename to find a parser for.

    Returns:
        Parser class, or None if no parser matches.
    """
    basename = filename.rsplit("/", 1)[-1] if "/" in filename else filename
    # Check exact filename match first (skill.json, settingsmeta.*)
    if basename in PARSERS:
        return PARSERS[basename]
    # Check extension match
    for ext, parser in PARSERS.items():
        if ext.startswith(".") and basename.endswith(ext):
            return parser
    return None


__all__ = [
    "ParsedFile",
    "ParsedLine",
    "IntentParser",
    "VocabParser",
    "DialogParser",
    "EntityParser",
    "RegexParser",
    "ValueParser",
    "SkillJsonParser",
    "SettingsMetaParser",
    "PARSERS",
    "get_parser",
]
