"""Context card builder — generates translator-facing context from AST analysis.

Produces structured context cards that explain what a locale file does,
how it's used in skill code, and translation tips per file type.
"""

from dataclasses import dataclass, field
from typing import Any

from ovos_localize.analyzers.ast_analyzer import SkillAnalysis
from ovos_localize.enums import FileType
from ovos_localize.sync.github import ScannedFile


@dataclass
class ContextCard:
    """Translator-facing context card for a locale file.

    Attributes:
        file_name: The locale filename.
        file_type_label: Human-readable file type.
        intent_system: 'PADATIOUS', 'ADAPT', or None.
        handler_method: Python method that uses this file.
        handler_file: Python source file.
        handler_line: Line number.
        triggers_dialog: Dialog files triggered by the handler.
        slots: Slot/variable names in the file.
        slot_descriptions: What each slot represents.
        related_files: Other locale files connected to this one.
        builder_chain: Adapt IntentBuilder chain (if applicable).
        tips: Translation tips specific to this file type.
        used_by_intents: For .voc files — which intents use this keyword.
    """

    file_name: str
    file_type_label: str
    intent_system: str | None = None
    handler_method: str | None = None
    handler_file: str | None = None
    handler_line: int | None = None
    triggers_dialog: list[str] = field(default_factory=list)
    slots: list[str] = field(default_factory=list)
    slot_descriptions: dict[str, str] = field(default_factory=dict)
    related_files: list[str] = field(default_factory=list)
    builder_chain: dict[str, Any] | None = None
    tips: list[str] = field(default_factory=list)
    used_by_intents: list[str] = field(default_factory=list)
    handler_source: str | None = None


# Per-file-type translation tips
_TIPS: dict[FileType, list[str]] = {
    FileType.INTENT: [
        "Provide 10+ natural phrasings with varied sentence structure.",
        "Keep all {slot} placeholders exactly as in the source.",
        "Use (option1|option2) for alternative words.",
        "Vary sentence beginnings — don't start every line the same way.",
    ],
    FileType.VOCAB: [
        "Use short keywords (1-3 words), not full sentences.",
        "Include common synonyms in the target language.",
        "One keyword per line.",
    ],
    FileType.DIALOG: [
        "Keep all {variable} placeholders exactly as in the source.",
        "Provide 2+ variant lines for natural speech variety.",
        "These are spoken aloud by TTS — write naturally.",
    ],
    FileType.ENTITY: [
        "Provide 5+ example values.",
        "Examples should be representative of the entity type.",
    ],
    FileType.REGEX: [
        "Keep (?P<Name>...) group names unchanged.",
        "Translate prepositions and trigger words around the groups.",
        "Test your regex against sample sentences.",
    ],
    FileType.VALUE: [
        "Only translate the left column (display name).",
        "The right column (system value) must stay unchanged.",
    ],
}


def build_context_card(
    scanned: ScannedFile,
    analysis: SkillAnalysis | None = None,
    all_files: list[ScannedFile] | None = None,
) -> ContextCard:
    """Build a context card for a scanned locale file.

    Args:
        scanned: The scanned locale file.
        analysis: Skill AST analysis (if available).
        all_files: All locale files in the skill (for cross-references).

    Returns:
        ContextCard with contextual information for translators.
    """
    card = ContextCard(
        file_name=scanned.base_name,
        file_type_label=_file_type_label(scanned.file_type),
        tips=_TIPS.get(scanned.file_type, []),
    )

    if scanned.parsed:
        card.slots = scanned.parsed.all_slots

    if not analysis:
        return card

    # .intent files → find handler
    if scanned.file_type == FileType.INTENT:
        intent_key = scanned.base_name + ".intent"
        handler = analysis.intent_file_to_handler.get(intent_key)
        if handler:
            card.intent_system = "PADATIOUS"
            card.handler_method = handler.method_name
            card.handler_file = handler.file_path
            card.handler_line = handler.line_number
            card.handler_source = handler.source_code or analysis.method_sources.get(handler.method_name)

            # Find dialogs triggered by this handler
            for dialog_call in analysis.dialog_calls:
                if dialog_call.method_name == handler.method_name:
                    card.triggers_dialog.append(dialog_call.dialog_name)
                    for var in dialog_call.variables:
                        card.slot_descriptions[var] = f"Variable passed to {dialog_call.dialog_name}.dialog"

    # .voc files → find Adapt intents using this keyword
    elif scanned.file_type == FileType.VOCAB:
        intents = analysis.voc_to_intents.get(scanned.base_name, [])
        if intents:
            card.intent_system = "ADAPT"
            card.used_by_intents = intents
            # Find the first handler that uses this keyword
            for handler in analysis.intent_handlers:
                if handler.intent_type == "adapt" and scanned.base_name in (
                    handler.required_keywords + handler.optional_keywords
                ):
                    card.handler_method = handler.method_name
                    card.handler_file = handler.file_path
                    card.handler_line = handler.line_number
                    card.handler_source = handler.source_code or analysis.method_sources.get(handler.method_name)
                    card.builder_chain = {
                        "name": handler.builder_name,
                        "require": handler.required_keywords,
                        "optionally": handler.optional_keywords,
                        "one_of": handler.one_of_keywords,
                    }
                    break

    # .dialog files → find callers
    elif scanned.file_type == FileType.DIALOG:
        callers = analysis.dialog_to_callers.get(scanned.base_name, [])
        if callers:
            card.handler_method = callers[0]
            card.handler_source = analysis.method_sources.get(callers[0])
            # Find variables from speak_dialog calls
            for call in analysis.dialog_calls:
                if call.dialog_name == scanned.base_name:
                    for var in call.variables:
                        card.slot_descriptions[var] = f"Runtime value from {call.method_name}()"

    # .rx files → find named groups
    elif scanned.file_type == FileType.REGEX:
        card.intent_system = "ADAPT"

    # Cross-reference related files
    if all_files:
        card.related_files = _find_related_files(scanned, all_files, analysis)

    return card


def _file_type_label(ft: FileType) -> str:
    """Human-readable label for a file type.

    Args:
        ft: FileType enum value.

    Returns:
        Label string.
    """
    labels = {
        FileType.INTENT: "Padatious Intent (training utterances)",
        FileType.VOCAB: "Adapt Keyword (vocabulary)",
        FileType.DIALOG: "Dialog (TTS response variants)",
        FileType.ENTITY: "Entity (slot examples)",
        FileType.REGEX: "Regex (entity extraction pattern)",
        FileType.VALUE: "Named Value (display → system mapping)",
        FileType.SKILL_JSON: "Skill Metadata (JSON)",
        FileType.SETTINGS_META: "Settings Metadata",
        FileType.NOISE_WORDS: "Noise Words (stopwords)",
        FileType.WORD_CONNECTORS: "Word Connectors (and/or/etc.)",
    }
    return labels.get(ft, str(ft))


def _find_related_files(
    scanned: ScannedFile,
    all_files: list[ScannedFile],
    analysis: SkillAnalysis | None,
) -> list[str]:
    """Find locale files related to this one.

    Args:
        scanned: The file to find relations for.
        all_files: All locale files.
        analysis: Skill analysis.

    Returns:
        List of related file paths.
    """
    related: list[str] = []

    if not analysis:
        return related

    # Find handler method for this file
    handler_method = None
    if scanned.file_type == FileType.INTENT:
        handler = analysis.intent_file_to_handler.get(scanned.base_name + ".intent")
        if handler:
            handler_method = handler.method_name
    elif scanned.file_type == FileType.DIALOG:
        callers = analysis.dialog_to_callers.get(scanned.base_name, [])
        if callers:
            handler_method = callers[0]

    if not handler_method:
        return related

    # Find all dialog files called by same handler
    for call in analysis.dialog_calls:
        if call.method_name == handler_method:
            dialog_name = call.dialog_name + ".dialog"
            for f in all_files:
                if f.lang == scanned.lang and f.base_name == call.dialog_name:
                    if f.relative_path != scanned.relative_path:
                        related.append(f.relative_path)

    return list(set(related))
