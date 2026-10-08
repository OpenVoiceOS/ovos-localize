"""Template expansion and slot filling for the intents corpus.

A ``.intent`` line is a template. ``<name>`` in a template expands from
``name.voc`` of the same language. ``{name}`` is a slot: it fills from
``name.entity`` of the same language as hints, a typed slot fills from the
typed-slot parser for that language, and a slot with no values stays literal
(OVOS-INTENT-1 §5.4). A ``.voc`` file is never read as slot values.

The functions are the ones the ovos-m2v-pipeline builder uses
(``train/build_from_skills.py``), so a template expands to the same sentences
in both repositories.
"""
import collections
import itertools
import re
import string

from ovos_spec_tools.expansion import expand
from ovos_spec_tools.lint import declared_slot_types

from ovos_localize.corpus import typed_slots

#: A template producing more than this is a generator, not a phrasing.
EXPANSION_CAP = 2000


def strip_groups(text: str) -> str:
    """*text* with every balanced `(...)` and `[...]` group removed.

    Both are grammar: `(a|b)` is an alternation and `[a]` an optional
    segment, and the expander reads each correctly. What is left is the part
    of a line the grammar does not account for, so a `|` still in it belongs
    to nothing: the author wrote an alternation and left off its
    parentheses.
    """
    out = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def has_bare_alternation(text: str) -> bool:
    """A `|` none of the grammar's own groups covers.

    Only the pipe. An optional segment is legal template syntax that expands,
    so reading `[the]` as a defect drops thousands of sound templates and
    takes their labels with them -- the build's own label floor catches that,
    which is how this check was caught being too wide.
    """
    return "|" in strip_groups(text)


def split_bare_alternation(value: str) -> list:
    """The alternatives a resource value names, splitting a bare `|`.

    A value is one whole thing, so a `|` in it that no group covers separates
    two values the author wrote on one line -- `complet|ple|plena` is three
    Catalan words for one brightness setting. Substituted whole, it ships as
    the literal string `complet|ple|plena` in a training row, which teaches a
    model to say the pipe out loud. The scope is unambiguous here, unlike the
    same mistake in a template, so the value is split rather than dropped.
    """
    if not has_bare_alternation(value) or "|" not in strip_groups(value):
        return [value]
    parts, depth, current = [], 0, []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def normalize_utterance(text: str) -> str:
    """Lowercase and collapse whitespace, the narrower overlap comparison.

    Exact string match after this normalisation, nothing wider: not
    accent-insensitive, not semantic. Kept and reported alongside the
    punctuation-insensitive comparison below because the two answer
    different questions, and collapsing them into one number would hide
    which normalisation the removal actually rests on.
    """
    return re.sub(r"\s+", " ", text.strip()).lower()


def normalize_utterance_punct_insensitive(text: str) -> str:
    """As ``normalize_utterance``, plus stripping leading/trailing punctuation.

    ``ovos-utterance-normalizer``, the runtime transformer every incoming
    utterance passes through before an intent engine matches it, strips
    edge punctuation with ``utterance.strip(string.punctuation).strip()``.
    A gold row ending in "?" and a training expansion without one are the
    same string at that point, so the removal this builder performs is
    matched on this wider equivalence, not the narrower one above. Still
    not accent-insensitive, not semantic, and inner punctuation is left
    alone -- only what the runtime strips is stripped here.
    """
    return normalize_utterance(text).strip(string.punctuation).strip()


def normalize_lang(tag: str) -> str:
    """Canonical spelling of a BCP-47 tag, per OVOS-INTENT-2 2.

    Tag comparison is case-insensitive, so a locale directory's case is not
    part of a language's identity. Lowercase the primary and extended
    subtags, titlecase a 4-letter script, uppercase a 2-letter region; a
    3-digit region is a number and has no case to fold.
    """
    parts = tag.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 4 and part.isalpha():
            out.append(part.title())
        elif len(part) == 2 and part.isalpha():
            out.append(part.upper())
        else:
            out.append(part)
    return "-".join(out)


def fill(template: str, hints: dict, keywords: dict, stats: collections.Counter,
         lang: str = "en-US"):
    """Sentences a template produces, with its own language's resources.

    `<name>` references a keyword file, which is how a template says "any of
    these words here". `{name}` is a slot: filled from the language's hints
    when it has them, and left unfilled otherwise -- an unfilled slot is a
    phrasing this corpus cannot use, not a phrasing the skill cannot match.
    """
    # `expand` strips a type prefix, so `{number:offset}` reaches the loop
    # below as `{offset}` and the type is only knowable from the template
    # itself (OVOS-INTENT-4 6.1).
    try:
        slot_types = declared_slot_types([template]) or {}
    except Exception:
        slot_types = {}
    try:
        sentences = expand(template, keywords)
    except Exception:
        stats["template_would_not_expand"] += 1
        return []
    if len(sentences) > EXPANSION_CAP:
        stats["template_over_cap"] += 1
        sentences = sentences[:EXPANSION_CAP]
    out = []
    for s in sentences:
        slots = {n.lower() for n in re.findall(r"\{([^}]+)\}", s)}
        if not slots:
            out.append(s)
            continue
        # A slot with no examples is not a dead template. INTENT-1 5.2 makes
        # a slot free-form capture, 5.4 says a slot with no value set still
        # fills, and the runtime agrees: `expand_entities` passes a sample
        # through with the placeholder left literal and embeds it that way.
        # The corpus mirrors the runtime rather than discarding the phrasing.
        # A typed slot is filled from the parser for its type in THIS
        # language, never from an .entity and never left as a brace: the
        # runtime binds it by asking that same parser, so a row carrying the
        # placeholder teaches a surface the runtime never produces. A type
        # with no generator for this language drops the sentence rather than
        # filling it with another language's words.
        typed_here = {n: slot_types[n] for n in slots if n in slot_types}
        if typed_here:
            values = {n: typed_slots.values_for(t, lang)
                      for n, t in typed_here.items()}
            if not all(values.values()):
                stats["sentence_dropped_no_typed_values_for_this_language"] += 1
                continue
            partials = [s]
            for name, produced in values.items():
                grown = []
                for partial in partials:
                    for value in produced:
                        grown.append(re.sub(r"\{" + re.escape(name) + r"\}", value,
                                            partial, flags=re.IGNORECASE))
                partials = grown[:EXPANSION_CAP]
            stats["sentences_from_a_typed_slot"] += len(partials)
            slots = slots - set(typed_here)
            if not slots:
                out.extend(partials)
                continue
            # an untyped slot is left to the hint pass below, per sentence
            for partial in partials:
                out.extend(fill(partial, hints, keywords, stats, lang))
            continue

        if any(n not in hints for n in slots):
            stats["sentences_kept_with_an_unfilled_slot_before_filling"] += 1
        filled = [s]
        for slot in sorted(n for n in slots if n in hints):
            # The first EXPANSION_CAP sentences of the product, in product
            # order, without building the rest: two slots of a thousand hints
            # each are a million substitutions otherwise.
            pattern = re.compile(r"\{" + re.escape(slot) + r"\}", re.IGNORECASE)
            filled = list(itertools.islice(
                (pattern.sub(value, partial) for partial in filled for value in hints[slot]),
                EXPANSION_CAP))
        # A hint value is substituted verbatim, and a value can itself carry
        # template syntax (an `.entity` line copied from a template, or one
        # written with alternation in it). Left alone, that syntax ships as a
        # literal training row instead of the sentences it denotes, so every
        # filled string is expanded again. `expand` is eager and raises
        # rather than returning a partial sample set, so a fill that produces
        # a malformed string is dropped whole, the same way a malformed
        # template is dropped above -- never partially kept.
        reexpanded = []
        for f in filled:
            try:
                grown = expand(f, {})
            except Exception:
                stats["filled_sentence_would_not_expand"] += 1
                continue
            if len(grown) > 1:
                stats["rows_expanded_after_filling"] += len(grown)
            reexpanded.extend(grown)
        if len(reexpanded) > EXPANSION_CAP:
            stats["sentence_over_cap_after_fill"] += 1
            reexpanded = reexpanded[:EXPANSION_CAP]
        out.extend(reexpanded)
    return out
