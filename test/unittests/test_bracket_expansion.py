"""Unit tests for bracket expansion."""

from ovos_localize.bracket_expansion import (
    count_expanded_lines,
    expand_template,
    expand_template_cached,
)

# Produces 5 * 5 * 4 * 3 = 300 combinations — enough to exceed a small cap
# without ballooning test runtime.
_BIG_TEMPLATE = "(a|b|c|d|e) (1|2|3|4|5) (w|x|y|z) (p|q|r)"


class TestExpandTemplate:
    """Tests for expand_template()."""

    def test_no_expansion(self) -> None:
        """Plain text returns unchanged."""
        assert expand_template("hello world") == ["hello world"]

    def test_alternatives(self) -> None:
        """(a|b) groups expand to alternatives."""
        result = expand_template("(hello|hi) world")
        assert sorted(result) == ["hello world", "hi world"]

    def test_optional(self) -> None:
        """[optional] groups expand to with/without."""
        result = expand_template("test [please]")
        assert sorted(result) == ["test", "test please"]

    def test_multiple_groups(self) -> None:
        """Multiple groups produce cartesian product."""
        result = expand_template("(a|b) (1|2)")
        assert sorted(result) == ["a 1", "a 2", "b 1", "b 2"]

    def test_slots_preserved(self) -> None:
        """{slots} are not expanded."""
        result = expand_template("play {song} by (the|) {artist}")
        assert len(result) == 2
        assert all("{song}" in r and "{artist}" in r for r in result)

    def test_empty_alternative(self) -> None:
        """Empty alternative (a|) produces with/without."""
        result = expand_template("(the|) weather")
        assert sorted(result) == ["the weather", "weather"]

    def test_three_alternatives(self) -> None:
        """Three-way alternative."""
        result = expand_template("(tell|show|give) me")
        assert len(result) == 3


class TestMaxExpansions:
    """Tests for the ``max_expansions`` cap on expand_template()."""

    def test_unbounded_default_unchanged(self) -> None:
        """Without a cap, full expansion behaviour is unchanged (300 combos)."""
        full = expand_template(_BIG_TEMPLATE)
        assert len(full) == 300
        assert len(set(full)) == 300

    def test_cap_limits_result_size(self) -> None:
        """A cap smaller than the full product truncates the result."""
        capped = expand_template(_BIG_TEMPLATE, max_expansions=50)
        assert len(capped) <= 50
        assert len(capped) > 0

    def test_cap_larger_than_product_is_a_no_op(self) -> None:
        """A cap bigger than the full product changes nothing."""
        full = expand_template(_BIG_TEMPLATE)
        capped = expand_template(_BIG_TEMPLATE, max_expansions=10_000)
        assert capped == full

    def test_capped_sample_is_valid_subset(self) -> None:
        """Sampled combos are real members of the full (uncapped) expansion."""
        full = set(expand_template(_BIG_TEMPLATE))
        capped = expand_template(_BIG_TEMPLATE, max_expansions=50)
        assert set(capped) <= full

    def test_cap_is_deterministic(self) -> None:
        """The same template + cap always produces the same sample."""
        first = expand_template(_BIG_TEMPLATE, max_expansions=50)
        second = expand_template(_BIG_TEMPLATE, max_expansions=50)
        assert first == second

    def test_astronomically_large_product_does_not_error(self) -> None:
        """A product far bigger than sys.maxsize is still sampled, not crashed.

        Real skill data (e.g. ovos-skill-wallpapers) produces templates with
        chained alternative groups whose expansion count vastly exceeds what
        fits in a C ssize_t, which random.sample(range(n), k) cannot handle
        directly.
        """
        groups = " ".join(f"(a{i}|b{i}|c{i}|d{i})" for i in range(40))  # 4**40 combos
        capped = expand_template(groups, max_expansions=50)
        assert len(capped) == 50
        assert len(set(capped)) == 50

    def test_different_templates_can_sample_differently(self) -> None:
        """The seed is derived from the template text, not a fixed constant."""
        a = expand_template(_BIG_TEMPLATE, max_expansions=50)
        b = expand_template("(p|q|r) (w|x|y|z) (1|2|3|4|5) (a|b|c|d|e)", max_expansions=50)
        assert a != b


class TestExpandTemplateCached:
    """Tests for the memoized expand_template_cached() wrapper."""

    def test_matches_uncached(self) -> None:
        """Cached result matches an equivalent uncapped call."""
        assert list(expand_template_cached(_BIG_TEMPLATE, None)) == expand_template(_BIG_TEMPLATE)

    def test_matches_capped_uncached(self) -> None:
        """Cached result matches an equivalent capped call."""
        assert list(expand_template_cached(_BIG_TEMPLATE, 50)) == expand_template(
            _BIG_TEMPLATE, max_expansions=50
        )

    def test_repeated_calls_are_memoized(self) -> None:
        """Calling twice with the same args returns the identical cached object."""
        first = expand_template_cached("(hello|hi) world", 200)
        second = expand_template_cached("(hello|hi) world", 200)
        assert first is second


class TestCountExpandedLines:
    """Tests for count_expanded_lines()."""

    def test_simple_lines(self) -> None:
        """Lines without alternatives count as-is."""
        assert count_expanded_lines(["hello", "world"]) == 2

    def test_with_alternatives(self) -> None:
        """Lines with alternatives expand."""
        assert count_expanded_lines(["(a|b) test"]) == 2

    def test_skips_comments(self) -> None:
        """Comment lines are skipped."""
        assert count_expanded_lines(["# comment", "hello"]) == 1

    def test_skips_blank(self) -> None:
        """Blank lines are skipped."""
        assert count_expanded_lines(["", "  ", "hello"]) == 1

    def test_empty(self) -> None:
        """Empty input returns 0."""
        assert count_expanded_lines([]) == 0
