"""Unit tests for validation rules."""


from ovos_localize.parsers.dialog import DialogParser
from ovos_localize.parsers.entity import EntityParser
from ovos_localize.parsers.intent import IntentParser
from ovos_localize.parsers.regex import RegexParser
from ovos_localize.parsers.value import ValueParser
from ovos_localize.parsers.vocab import VocabParser
from ovos_localize.validators.rules import (
    validate_dialog,
    validate_entity,
    validate_file,
    validate_intent,
    validate_regex,
    validate_value,
    validate_vocab,
)


class TestIntentValidation:
    """Tests for .intent file validation rules."""

    def test_min_lines_warning(self) -> None:
        """Warn when intent file expands to fewer than 10 sentences."""
        content = "\n".join([f"utterance {i}" for i in range(5)])
        parsed = IntentParser().parse_content(content)
        issues = validate_intent(parsed)
        assert any(i.rule_name == "intent.min_lines" for i in issues)

    def test_min_lines_passes(self) -> None:
        """No warning when intent file has 10+ expanded sentences."""
        content = "\n".join([f"unique utterance number {i} here" for i in range(12)])
        parsed = IntentParser().parse_content(content)
        issues = validate_intent(parsed)
        assert not any(i.rule_name == "intent.min_lines" for i in issues)

    def test_min_lines_with_alternatives(self) -> None:
        """Templates with (a|b|c) alternatives expand to enough sentences."""
        # 3 templates × 4 alternatives each = 12 expanded sentences → passes
        content = "(tell|show|give) me the (weather|forecast|temperature|conditions)\nwhat is the (weather|forecast)\nhow is the weather"
        parsed = IntentParser().parse_content(content)
        issues = validate_intent(parsed)
        assert not any(i.rule_name == "intent.min_lines" for i in issues)

    def test_missing_slots(self) -> None:
        """Error when translation is missing slots from source."""
        source = IntentParser().parse_content("play {song} by {artist}\n")
        translated = IntentParser().parse_content("spiele {song}\n")
        issues = validate_intent(translated, source)
        assert any(
            i.rule_name == "intent.missing_slots" and i.severity == "error"
            for i in issues
        )

    def test_slots_preserved(self) -> None:
        """No error when all slots preserved."""
        source = IntentParser().parse_content("play {song}\n")
        translated = IntentParser().parse_content("spiele {song}\n")
        issues = validate_intent(translated, source)
        assert not any(i.rule_name == "intent.missing_slots" for i in issues)

    def test_slot_only_line_is_not_rejected(self) -> None:
        """A bare slot line is legal Padatious syntax and must not error.

        Common Play ships slot-only .intent lines upstream, e.g.
        ovos-ocp-audio-plugin's ru-ru/tr-tr/hu-hu locales use a bare
        ``{query}`` line to match "play <query>" style utterances.
        """
        parsed = IntentParser().parse_content("play {song} by {artist}\n{song}\n")
        issues = validate_intent(parsed)
        assert not any(i.rule_name == "slot_only_line" for i in issues)

    def test_unbalanced_parens(self) -> None:
        """Error on unbalanced parentheses."""
        parsed = IntentParser().parse_content("play (some music\n")
        issues = validate_intent(parsed)
        assert any(i.rule_name == "intent.unbalanced_parens" for i in issues)


class TestVocabValidation:
    """Tests for .voc file validation rules."""

    def test_empty_file_error(self) -> None:
        """Error on empty vocab file."""
        parsed = VocabParser().parse_content("")
        issues = validate_vocab(parsed)
        assert any(i.rule_name == "vocab.empty" for i in issues)

    def test_long_keyword_warning(self) -> None:
        """Warn when a keyword is too long (>5 words)."""
        parsed = VocabParser().parse_content(
            "this is way too many words for a keyword\n"
        )
        issues = validate_vocab(parsed)
        assert any(i.rule_name == "vocab.long_keyword" for i in issues)

    def test_short_keywords_pass(self) -> None:
        """No warning for short keywords."""
        parsed = VocabParser().parse_content("weather\nforecast\n")
        issues = validate_vocab(parsed)
        assert not any(i.rule_name == "vocab.long_keyword" for i in issues)


class TestDialogValidation:
    """Tests for .dialog file validation rules."""

    def test_missing_variables(self) -> None:
        """Error when translation is missing variables."""
        source = DialogParser().parse_content("It is {time} in {location}\n")
        translated = DialogParser().parse_content("Es ist {time}\n")
        issues = validate_dialog(translated, source)
        assert any(i.rule_name == "dialog.missing_variables" for i in issues)

    def test_extra_variables(self) -> None:
        """Error when translation has extra variables."""
        source = DialogParser().parse_content("Hello {name}\n")
        translated = DialogParser().parse_content("Hallo {name} {extra}\n")
        issues = validate_dialog(translated, source)
        assert any(i.rule_name == "dialog.extra_variables" for i in issues)

    def test_slot_only_dialog_line_passes(self) -> None:
        """A dialog line that is only a variable placeholder must not error.

        Regression: ovos-skill-alerts/locale/*/dialog/at_time.dialog ships
        a bare ``{begin}`` line in 20+ locales, and
        ovos-skill-personal's where.was.i.born.dialog is exactly
        ``{location}``. Rejecting these would break real skills.
        """
        parsed = DialogParser().parse_content("{begin}\n")
        issues = validate_dialog(parsed)
        assert not any(i.rule_name == "slot_only_line" for i in issues)

    def test_few_variants_warning(self) -> None:
        """Warn when dialog has only one variant."""
        parsed = DialogParser().parse_content("Hello\n")
        issues = validate_dialog(parsed)
        assert any(i.rule_name == "dialog.few_variants" for i in issues)


class TestEntityValidation:
    """Tests for .entity file validation rules."""

    def test_few_examples_warning(self) -> None:
        """Warn when entity file has fewer than 5 examples."""
        parsed = EntityParser().parse_content("red\nblue\n")
        issues = validate_entity(parsed)
        assert any(i.rule_name == "entity.few_examples" for i in issues)

    def test_slot_only_line_rejected(self) -> None:
        """Error when an entity file line is just a slot placeholder.

        Regression for ovos-skill-date-time#282: locale/kab/date.entity line 3
        was ``{date}``, which is not a valid entity example.
        """
        parsed = EntityParser().parse_content("today\ntomorrow\nyesterday\nnow\n{date}\n")
        issues = validate_entity(parsed)
        assert any(
            i.rule_name == "slot_only_line" and i.severity == "error"
            for i in issues
        )

    def test_normal_examples_pass(self) -> None:
        """No slot_only_line error for plain literal entity examples."""
        parsed = EntityParser().parse_content("today\ntomorrow\nyesterday\nnow\nnext week\n")
        issues = validate_entity(parsed)
        assert not any(i.rule_name == "slot_only_line" for i in issues)


class TestRegexValidation:
    """Tests for .rx file validation rules."""

    def test_compile_error(self) -> None:
        """Error on invalid regex."""
        parsed = RegexParser().parse_content("[invalid\n")
        issues = validate_regex(parsed)
        assert any(i.rule_name == "regex.compile_error" for i in issues)

    def test_missing_named_groups(self) -> None:
        """Error when translation is missing named groups."""
        source = RegexParser().parse_content(r"(?P<Location>.*)" + "\n")
        translated = RegexParser().parse_content(r"(.*)" + "\n")
        issues = validate_regex(translated, source)
        assert any(i.rule_name == "regex.missing_named_groups" for i in issues)


class TestValueValidation:
    """Tests for .value file validation rules."""

    def test_parse_error(self) -> None:
        """Error on invalid CSV format."""
        parsed = ValueParser().parse_content("no comma\n")
        issues = validate_value(parsed)
        assert any(i.rule_name == "value.parse_error" for i in issues)

    def test_missing_system_values(self) -> None:
        """Error when translation is missing system values."""
        source = ValueParser().parse_content("China,Etc/GMT+8\nJapan,Asia/Tokyo\n")
        translated = ValueParser().parse_content("China,Etc/GMT+8\n")
        issues = validate_value(translated, source)
        assert any(i.rule_name == "value.missing_system_values" for i in issues)


class TestValidateFileDispatch:
    """Tests for the validate_file dispatch function."""

    def test_dispatches_to_intent(self) -> None:
        """Correctly dispatches to intent validator."""
        parsed = IntentParser().parse_content("test\n")
        issues = validate_file(parsed)
        # Should run intent validator (will get min_lines warning)
        assert any(i.rule_name.startswith("intent.") for i in issues)

    def test_unknown_type_returns_empty(self) -> None:
        """Unknown file types return no issues."""
        from ovos_localize.parsers.base import ParsedFile
        parsed = ParsedFile(path="test", file_type="unknown_type")
        issues = validate_file(parsed)
        assert issues == []
