"""Bracket/parentheses expansion for OVOS locale templates.

Expands ``(a|b)`` alternative groups and ``[optional]`` groups into
all possible sentence combinations. Pure stdlib implementation
compatible with ``ovos_utils.bracket_expansion.expand_template``.

Examples:
    >>> expand_template("(hello|hi) world")
    ['hello world', 'hi world']
    >>> expand_template("test [please]")
    ['test', 'test please']
    >>> expand_template("play {song} by (the|) {artist}")
    ['play {song} by  {artist}', 'play {song} by the {artist}']
"""

import itertools
import re


def expand_template(template: str) -> list[str]:
    """Expand a template string into all possible utterances.

    Handles:
    - ``(option1|option2|option3)`` — alternative groups
    - ``[optional text]`` — optional groups (expanded to with/without)

    Args:
        template: Template string with alternatives and optionals.

    Returns:
        Sorted list of unique expanded sentences.
    """
    # [optional] → (optional|)
    t = re.sub(r"\[([^\[\]]+)\]", r"(\1|)", template)

    def _expand_alternatives(text: str) -> list[str]:
        parts = []
        for segment in re.split(r"(\([^()]+\))", text):
            if segment.startswith("(") and segment.endswith(")"):
                parts.append(segment[1:-1].split("|"))
            else:
                parts.append([segment])
        return [
            re.sub(r"\s+", " ", "".join(combo)).strip()
            for combo in itertools.product(*parts)
        ]

    # Iteratively expand until stable
    result = {t}
    for _ in range(10):  # safety limit for nested groups
        expanded = set()
        for text in result:
            expanded.update(_expand_alternatives(text))
        if expanded == result:
            break
        result = expanded

    return sorted(s for s in result if s.strip())


def clean_text(text: str) -> str:
    """Clean text for ML datasets: lowercase, remove extra whitespace.

    Args:
        text: Raw utterance.

    Returns:
        Cleaned, lowercased string.
    """
    import re
    # Lowercase and remove punctuation (optional? user didn't ask but typical)
    # Keeping it simple as requested: whitespace and lowercase
    text = text.lower().strip()
    # Replace multiple whitespaces with single space
    text = re.sub(r"\s+", " ", text)
    return text


def count_expanded_lines(lines: list[str]) -> int:
    """Count the total number of expanded sentences from a list of template lines.

    Skips blank lines and comments.

    Args:
        lines: Raw template lines (e.g. from a .intent file).

    Returns:
        Total number of unique expanded sentences.
    """
    total = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        total += len(expand_template(stripped))
    return total
