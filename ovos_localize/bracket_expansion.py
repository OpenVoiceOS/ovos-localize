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

import functools
import hashlib
import itertools
import random
import re
import sys

# Default cap for dataset generators (see expand_template_cached). Pathological
# templates with several nested alternative groups can otherwise produce tens
# of thousands of combinations for a single line and OOM the generator process.
MAX_TEMPLATE_EXPANSIONS = 200

# Running count of how many distinct templates hit the cap during this
# process's lifetime, for the generators' end-of-run summary line. Only
# capped (max_expansions is not None) calls that actually exceeded the cap
# increment this. See reset_truncation_count().
_truncation_count = 0


def reset_truncation_count() -> None:
    """Reset the truncated-template counter (see truncation_count())."""
    global _truncation_count
    _truncation_count = 0


def truncation_count() -> int:
    """Number of distinct templates whose expansion was capped/sampled so far."""
    return _truncation_count


def _seeded_sample_indices(seed_text: str, population: int, k: int) -> list[int]:
    """Deterministically pick *k* distinct indices from ``range(population)``.

    The sample is seeded from a hash of *seed_text* (not the builtin
    ``hash()``, which is randomized per-process) so the same template always
    yields the same sample across runs.
    """
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)
    if population <= sys.maxsize:
        # rng.sample() is the well-tested path; use it whenever `range()`
        # can report its own length (CPython requires this to fit a C
        # ssize_t).
        return rng.sample(range(population), k)

    # `population` can be astronomically large (deeply nested alternative
    # groups multiply out combinatorially), too big for `range(population)`
    # to be indexable. Draw distinct indices directly with rng.randrange(),
    # which supports arbitrary-precision bounds.
    chosen: set[int] = set()
    while len(chosen) < k:
        chosen.add(rng.randrange(population))
    return list(chosen)


def _expand_alternatives(text: str, max_expansions: int | None) -> list[str]:
    parts: list[list[str]] = []
    for segment in re.split(r"(\([^()]+\))", text):
        if segment.startswith("(") and segment.endswith(")"):
            parts.append(segment[1:-1].split("|"))
        else:
            parts.append([segment])

    total = 1
    for p in parts:
        total *= len(p)

    if max_expansions is None or total <= max_expansions:
        combos = itertools.product(*parts)
    else:
        # Too big to materialize the full product: deterministically sample
        # `max_expansions` combos by decoding sampled indices into the
        # mixed-radix product space, without ever building the full product.
        sizes = [len(p) for p in parts]
        indices = _seeded_sample_indices(text, total, max_expansions)
        combos = []
        for idx in indices:
            combo = []
            remainder = idx
            for size, options in zip(sizes, parts):
                remainder, choice = divmod(remainder, size)
                combo.append(options[choice])
            combos.append(combo)

    return [
        re.sub(r"\s+", " ", "".join(combo)).strip()
        for combo in combos
    ]


def expand_template(template: str, max_expansions: int | None = None) -> list[str]:
    """Expand a template string into all possible utterances.

    Handles:
    - ``(option1|option2|option3)`` — alternative groups
    - ``[optional text]`` — optional groups (expanded to with/without)

    Args:
        template: Template string with alternatives and optionals.
        max_expansions: If set, caps the number of expansions produced per
            expansion pass. When a pass would exceed the cap, a deterministic
            sample (seeded by the input text) is taken instead of the full
            cartesian product, so results stay reproducible across runs while
            avoiding unbounded memory/time blowups on pathological templates.
            ``None`` (the default) preserves full, unbounded expansion.

    Returns:
        Sorted list of unique expanded sentences.
    """
    # [optional] → (optional|)
    t = re.sub(r"\[([^\[\]]+)\]", r"(\1|)", template)

    was_truncated = False

    # Iteratively expand until stable
    result = {t}
    for _ in range(10):  # safety limit for nested groups
        expanded = set()
        for text in result:
            expanded.update(_expand_alternatives(text, max_expansions))
        if max_expansions is not None and len(expanded) > max_expansions:
            was_truncated = True
            sample_idx = set(
                _seeded_sample_indices(t, len(expanded), max_expansions)
            )
            expanded = {s for i, s in enumerate(sorted(expanded)) if i in sample_idx}
        if expanded == result:
            break
        result = expanded

    if was_truncated:
        global _truncation_count
        _truncation_count += 1

    return sorted(s for s in result if s.strip())


@functools.lru_cache(maxsize=None)
def expand_template_cached(template: str, max_expansions: int | None = None) -> tuple[str, ...]:
    """Memoized wrapper around :func:`expand_template`.

    Dataset generators call ``expand_template`` on the same template text
    repeatedly (once per generator, and sometimes more than once within a
    single generator). This caches the result per ``(template,
    max_expansions)`` pair for the lifetime of the process, so repeated calls
    are free.

    Returns:
        Tuple of expanded sentences (tuples are hashable/cacheable; callers
        that need a list can wrap with ``list(...)``).
    """
    return tuple(expand_template(template, max_expansions))


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
