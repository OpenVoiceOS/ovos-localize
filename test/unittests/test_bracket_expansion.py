"""Unit tests for bracket expansion."""

from ovos_localize.bracket_expansion import expand_template, count_expanded_lines


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
