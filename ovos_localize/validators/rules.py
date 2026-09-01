"""Validation rules for each OVOS locale file type.

Each validator takes a ParsedFile (translated) and optionally the source
ParsedFile (en-us), returning a list of ValidationIssue objects.
"""

import re
from dataclasses import dataclass

from ovos_localize.bracket_expansion import count_expanded_lines
from ovos_localize.parsers.base import ParsedFile
from ovos_localize.parsers.intent import IntentParser


@dataclass
class ValidationIssue:
    """A single validation issue.

    Attributes:
        rule_name: Machine-readable rule identifier.
        severity: 'error', 'warning', or 'info'.
        message: Human-readable description.
        line_number: Optional line number reference.
    """

    rule_name: str
    severity: str  # "error", "warning", "info"
    message: str
    line_number: int | None = None


_SLOT_ONLY_RE = re.compile(r"^(?:\s|[^\w{}]|\{\w+\})+$")
_SLOT_TOKEN_RE = re.compile(r"\{[^{}]*\}")


def check_slot_only_lines(translated: ParsedFile) -> list[ValidationIssue]:
    """Reject .entity examples made up entirely of {slot} tokens.

    A line like ``{date}`` in a .entity file carries no fixed wording, so
    it can never be an example value for the entity it defines.

    Intent, vocab, and dialog lines that are only a slot placeholder are
    legitimate and ship upstream (e.g. Common Play ``{query}`` intents,
    ``{begin}`` alert dialogs, ``{location}`` personal-info dialogs), so
    this check applies to .entity only — callers should not use it for
    other file types.

    Args:
        translated: Parsed translated .entity file.

    Returns:
        List of validation issues (one error per offending line).
    """
    issues: list[ValidationIssue] = []
    for ln in translated.content_lines:
        if "{" not in ln.text:
            continue
        if _SLOT_ONLY_RE.match(ln.text):
            issues.append(ValidationIssue(
                rule_name="slot_only_line",
                severity="error",
                message=f"Line consists only of slot placeholder(s) and no literal text: {ln.text!r}",
                line_number=ln.line_number,
            ))
    return issues


def check_context_bleed_lines(translated: ParsedFile) -> list[ValidationIssue]:
    """Reject .entity/.voc lines that carry a {slot} placeholder.

    An .entity/.voc submission is a flat list of example values (e.g.
    ``12/25/2024`` or ``please``); it never carries a ``{slot}``
    placeholder — that is intent/dialog syntax, not a literal value. The
    translation editor shows dialog and intent lines that reference a slot
    as read-only context next to the entity's value box (see
    ``entityContextIntents`` in index.html); when a translator pastes that
    context panel into the value box instead of extracting example values
    from it, the .entity file ends up holding a mangled slot template
    verbatim. This is what caught the real shipping defect in
    ovos-skill-date-time's ``locale/it-IT/offset.entity``, whose lines were
    literally ``"che ora sarà tra {offset} minuti"`` — an intent phrasing,
    not an offset example.

    An earlier version of this rule also flagged lines containing
    sentence-ending punctuation or a comma, on the theory that dialog
    context reads like full sentences. That heuristic false-positived on
    hundreds of legitimate shipping .voc/.entity lines — question-style
    .voc entries (``"Podes parar agora?"``), and .entity date examples
    that are correctly punctuated (``"April 1st, 2023"``, ``"1. April
    2023"``, ``"mr. mime"``) — so it was removed; the {slot} check alone
    is precise over the corpus.

    Args:
        translated: Parsed translated .entity or .voc file.

    Returns:
        List of validation issues (one error per offending line).
    """
    issues: list[ValidationIssue] = []
    for ln in translated.content_lines:
        text = ln.text.strip()
        if not text:
            continue
        if _SLOT_TOKEN_RE.search(text):
            issues.append(ValidationIssue(
                rule_name="context_bleed",
                severity="error",
                message=f"Line {ln.text!r} contains a {{slot}} placeholder, not a plain example value.",
                line_number=ln.line_number,
            ))
    return issues


def validate_intent(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .intent file.

    Rules:
    - MIN_LINES: At least 10 expanded sentences (after bracket expansion).
    - SLOT_PRESERVATION: All source {slots} must appear in translation.
    - ALTERNATIVE_SYNTAX: All (a|b) groups must be valid.
    - LEXICAL_DIVERSITY: Diversity score >= 0.25.

    Args:
        translated: Parsed translated intent file.
        source: Parsed source (en-us) intent file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []
    content = translated.content_lines

    # MIN_LINES — count after template expansion (3 lines with (a|b|c) = 9 sentences)
    expanded_count = count_expanded_lines([ln.text for ln in content])
    if expanded_count < 10:
        issues.append(ValidationIssue(
            rule_name="intent.min_lines",
            severity="warning",
            message=f"Intent file expands to {expanded_count} sentences ({len(content)} templates); 10+ recommended for Padatious accuracy.",
        ))

    # SLOT_PRESERVATION
    if source:
        source_slots = set(source.all_slots)
        translated_slots = set(translated.all_slots)
        missing = source_slots - translated_slots
        extra = translated_slots - source_slots
        if missing:
            issues.append(ValidationIssue(
                rule_name="intent.missing_slots",
                severity="error",
                message=f"Missing slots from source: {{{', '.join(sorted(missing))}}}",
            ))
        if extra:
            issues.append(ValidationIssue(
                rule_name="intent.extra_slots",
                severity="warning",
                message=f"Extra slots not in source: {{{', '.join(sorted(extra))}}}",
            ))

    # ALTERNATIVE_SYNTAX
    for ln in content:
        # Check for unbalanced parentheses
        opens = ln.text.count("(")
        closes = ln.text.count(")")
        if opens != closes:
            issues.append(ValidationIssue(
                rule_name="intent.unbalanced_parens",
                severity="error",
                message="Unbalanced parentheses in alternative syntax.",
                line_number=ln.line_number,
            ))
        # Check for alternatives without pipe
        for match in re.finditer(r"\(([^)]+)\)", ln.text):
            group = match.group(1)
            if "|" not in group:
                issues.append(ValidationIssue(
                    rule_name="intent.no_pipe_in_alt",
                    severity="warning",
                    message=f"Parenthesized group without '|': ({group})",
                    line_number=ln.line_number,
                ))

    # LEXICAL_DIVERSITY
    diversity = IntentParser.compute_diversity(translated.lines)
    if diversity < 0.25:
        issues.append(ValidationIssue(
            rule_name="intent.low_diversity",
            severity="warning",
            message=f"Lexical diversity {diversity:.2f} is below 0.25 threshold.",
        ))

    return issues


def validate_vocab(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .voc file.

    Rules:
    - MIN_LINES: At least 1 content line.
    - LONG_KEYWORD: Warn if any line has >5 words (probably a sentence).

    Args:
        translated: Parsed translated vocab file.
        source: Parsed source (en-us) vocab file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []
    content = translated.content_lines

    if not content:
        issues.append(ValidationIssue(
            rule_name="vocab.empty",
            severity="error",
            message="Vocabulary file is empty; needs at least 1 keyword.",
        ))

    for ln in content:
        word_count = ln.metadata.get("word_count", len(ln.text.split()))
        if word_count > 5:
            issues.append(ValidationIssue(
                rule_name="vocab.long_keyword",
                severity="warning",
                message=f"Line has {word_count} words — vocab entries should be short keywords (1-3 words).",
                line_number=ln.line_number,
            ))

    issues.extend(check_context_bleed_lines(translated))

    return issues


def validate_dialog(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .dialog file.

    Rules:
    - VARIABLE_PRESERVATION: All source {variables} must appear.
    - NO_EXTRA_VARIABLES: No variables that aren't in source.
    - MIN_VARIANTS: At least 2 variant lines recommended.

    Args:
        translated: Parsed translated dialog file.
        source: Parsed source (en-us) dialog file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []
    content = translated.content_lines

    if len(content) < 2:
        issues.append(ValidationIssue(
            rule_name="dialog.few_variants",
            severity="warning",
            message=f"Dialog has {len(content)} variant(s); 2+ recommended for natural variation.",
        ))

    if source:
        source_vars = set(source.all_slots)
        translated_vars = set(translated.all_slots)
        missing = source_vars - translated_vars
        extra = translated_vars - source_vars
        if missing:
            issues.append(ValidationIssue(
                rule_name="dialog.missing_variables",
                severity="error",
                message=f"Missing variables from source: {{{', '.join(sorted(missing))}}}",
            ))
        if extra:
            issues.append(ValidationIssue(
                rule_name="dialog.extra_variables",
                severity="error",
                message=f"Extra variables not in source: {{{', '.join(sorted(extra))}}}",
            ))

    return issues


def validate_entity(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .entity file.

    Rules:
    - MIN_EXAMPLES: At least 5 examples recommended.

    Args:
        translated: Parsed translated entity file.
        source: Parsed source (en-us) entity file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []
    content = translated.content_lines

    if len(content) < 5:
        issues.append(ValidationIssue(
            rule_name="entity.few_examples",
            severity="warning",
            message=f"Entity file has {len(content)} examples; 5+ recommended.",
        ))

    issues.extend(check_slot_only_lines(translated))
    issues.extend(check_context_bleed_lines(translated))

    return issues


def validate_regex(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .rx file.

    Rules:
    - COMPILES: All regexes must compile.
    - NAMED_GROUPS: Named groups must match source.

    Args:
        translated: Parsed translated regex file.
        source: Parsed source (en-us) regex file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []

    for ln in translated.content_lines:
        if not ln.metadata.get("compiles", True):
            issues.append(ValidationIssue(
                rule_name="regex.compile_error",
                severity="error",
                message="Regex does not compile.",
                line_number=ln.line_number,
            ))

    if source:
        source_groups = set(source.all_slots)
        translated_groups = set(translated.all_slots)
        missing = source_groups - translated_groups
        if missing:
            issues.append(ValidationIssue(
                rule_name="regex.missing_named_groups",
                severity="error",
                message=f"Missing named groups from source: {', '.join(sorted(missing))}",
            ))

    return issues


def validate_value(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Validate a translated .value file.

    Rules:
    - VALID_CSV: Each line must be display,value format.
    - SYSTEM_VALUE_PRESERVED: Right column must match source.

    Args:
        translated: Parsed translated value file.
        source: Parsed source (en-us) value file.

    Returns:
        List of validation issues.
    """
    issues: list[ValidationIssue] = []

    # Inherit any parse errors
    for err in translated.errors:
        issues.append(ValidationIssue(
            rule_name="value.parse_error",
            severity="error",
            message=err,
        ))

    if source:
        source_values: set[str] = set()
        for ln in source.content_lines:
            sv = ln.metadata.get("system_value", "")
            if sv:
                source_values.add(sv)

        translated_values: set[str] = set()
        for ln in translated.content_lines:
            sv = ln.metadata.get("system_value", "")
            if sv:
                translated_values.add(sv)

        missing = source_values - translated_values
        if missing:
            issues.append(ValidationIssue(
                rule_name="value.missing_system_values",
                severity="error",
                message=f"Missing system values: {', '.join(sorted(missing))}",
            ))

    return issues


# Dispatch table: file_type → validator function
_VALIDATORS = {
    "intent": validate_intent,
    "voc": validate_vocab,
    "dialog": validate_dialog,
    "entity": validate_entity,
    "rx": validate_regex,
    "value": validate_value,
}


def validate_file(
    translated: ParsedFile, source: ParsedFile | None = None
) -> list[ValidationIssue]:
    """Run the appropriate validator for a parsed file.

    Args:
        translated: Parsed translated file.
        source: Parsed source (en-us) file.

    Returns:
        List of validation issues, or empty list if no validator for this type.
    """
    validator = _VALIDATORS.get(translated.file_type)
    if validator:
        return validator(translated, source)
    return []
