"""Property-based tests for template expansion (B4.1 — validation soundness).

These assert structural invariants of ``expand_template`` that must hold for
*any* well-formed template, not just hand-picked examples: slot preservation,
full bracket elimination, idempotence, and correct alternation cardinality.
"""

import re

from hypothesis import given
from hypothesis import strategies as st

from ovos_localize.bracket_expansion import expand_template

# Safe building blocks: lowercase words and {slot} placeholders — no bracket
# metacharacters, so generated templates are always well-formed.
words = st.text(alphabet="abcdefghij", min_size=1, max_size=5)
slots = words.map(lambda w: "{" + w + "}")
tokens = st.one_of(words, slots)
plain_templates = st.lists(tokens, min_size=1, max_size=5).map(" ".join)
distinct_words = st.lists(words, min_size=2, max_size=4, unique=True)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


@given(plain_templates)
def test_plain_text_is_identity(t):
    """A template with no groups expands to exactly its normalized self."""
    expected = [_norm(t)] if _norm(t) else []
    assert expand_template(t) == expected


@given(plain_templates)
def test_slots_preserved_in_every_expansion(t):
    """Every ``{slot}`` in the source appears in every expanded line."""
    source_slots = set(re.findall(r"\{[^}]+\}", t))
    # Wrap in an optional group so there is real expansion to check against.
    for line in expand_template(f"[maybe] {t}"):
        for slot in source_slots:
            assert slot in line


@given(st.lists(tokens, min_size=1, max_size=4).map(" ".join))
def test_no_bracket_chars_remain(t):
    """Output never contains unexpanded group delimiters."""
    for line in expand_template(f"({t}|other) [opt]"):
        assert not (set("()[]") & set(line))


@given(plain_templates)
def test_idempotent_on_expanded_output(t):
    """Re-expanding an already-expanded (group-free) line is a no-op."""
    for line in expand_template(t):
        assert expand_template(line) == [line]


@given(distinct_words)
def test_alternation_cardinality(alts):
    """``(a|b|c)`` yields exactly one line per distinct alternative."""
    template = "(" + "|".join(alts) + ")"
    assert len(expand_template(template)) == len(set(alts))


@given(words, words)
def test_optional_group_doubles(a, b):
    """``a [b]`` expands to both the with- and without-optional forms."""
    out = expand_template(f"{a} [{b}]")
    assert _norm(a) in out
    assert _norm(f"{a} {b}") in out
