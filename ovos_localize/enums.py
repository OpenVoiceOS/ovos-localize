"""Shared enums for OVOS locale file types and intent systems.

Extracted from models/locale_file.py to avoid SQLAlchemy dependency
for pure-Python consumers (CLI, scripts, GitHub Actions).
"""

import enum


class FileType(str, enum.Enum):
    """OVOS locale file types."""

    INTENT = "intent"
    VOCAB = "voc"
    DIALOG = "dialog"
    ENTITY = "entity"
    REGEX = "rx"
    VALUE = "value"
    SKILL_JSON = "skill.json"
    SETTINGS_META = "settingsmeta"
    NOISE_WORDS = "noise_words"
    WORD_CONNECTORS = "word_connectors"
    RESOURCE_JSON = "resource_json"


class IntentSystem(str, enum.Enum):
    """Intent matching system."""

    PADATIOUS = "padatious"
    ADAPT = "adapt"
    NONE = "none"
