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

    def test_context_bleed_rejected(self) -> None:
        """Error when a .voc submission carries a {slot} placeholder."""
        parsed = VocabParser().parse_content(
            "Uhu, {date} d {actual_weekday}, mačči d {weekday}.\n"
        )
        issues = validate_vocab(parsed)
        assert any(i.rule_name == "context_bleed" and i.severity == "error" for i in issues)

    def test_question_vocab_line_not_flagged_as_context_bleed(self) -> None:
        """A question-style .voc line without a {slot} must not be rejected.

        Regression: ovos-skill-stop and moon-game ship .voc entries like
        ``"Podes parar agora?"`` — a legitimate keyword-matching phrase,
        not dialog/intent context that leaked into the submission. An
        earlier version of this rule flagged sentence punctuation as a
        heuristic and rejected lines like this across ~99 shipping files.
        """
        parsed = VocabParser().parse_content("Podes parar agora?\n")
        issues = validate_vocab(parsed)
        assert not any(i.rule_name == "context_bleed" for i in issues)


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

    def test_context_bleed_rejected(self) -> None:
        """Error when an entity submission carries dialog/intent context.

        Regression for ovos-skill-date-time#282: the submitted
        ``locale/kab/date.entity`` content was a mix of dialog lines
        (``"Uhu, {date} d {actual_weekday}, mačči d {weekday}."``) and
        intent phrasings pasted from the read-only context panel, not
        plain date example values.
        """
        parsed = EntityParser().parse_content(
            "D {date}\n"
            "Uhu, {date} d {actual_weekday}, mačči d {weekday}.\n"
            "Bɣiɣ ad ẓreɣ anwa wass n umalas ay d {date}\n"
        )
        issues = validate_entity(parsed)
        assert any(i.rule_name == "context_bleed" and i.severity == "error" for i in issues)

    def test_plain_values_not_flagged_as_context_bleed(self) -> None:
        """No context_bleed error for plain literal entity examples."""
        parsed = EntityParser().parse_content("12/25/2024\n15th of May\n3 days ago\ntomorrow\nnext week\n")
        issues = validate_entity(parsed)
        assert not any(i.rule_name == "context_bleed" for i in issues)

    def test_punctuated_date_examples_not_flagged_as_context_bleed(self) -> None:
        """No context_bleed error for correctly punctuated date examples.

        Regression: ovos-skill-date-time ships ``locale/en-US/date.entity``
        lines like ``"April 1st, 2023"`` and ``locale/de-DE/date.entity``
        lines like ``"1. April 2023"``. An earlier version of this rule
        used a sentence-punctuation heuristic that rejected these — and
        hundreds of other legitimate lines across the corpus, including
        ``"mr. mime"`` in a Pokedex skill — alongside real slot-token
        defects, so the heuristic was dropped in favor of the {slot} check
        alone.
        """
        parsed = EntityParser().parse_content(
            "April 1st, 2023\n1. April 2023\n5. Mai 2023\ntomorrow\nnext week\n"
        )
        issues = validate_entity(parsed)
        assert not any(i.rule_name == "context_bleed" for i in issues)

    def test_slot_token_entity_line_still_rejected(self) -> None:
        """A {slot} placeholder in a shipping-shaped .entity line is still an error.

        Regression: ovos-skill-date-time's ``locale/it-IT/offset.entity``
        shipped lines like ``"che ora sarà tra {offset} minuti"`` — an
        intent phrasing, not an offset example value.
        """
        parsed = EntityParser().parse_content(
            "che ora sarà tra {offset} minuti\n"
            "che ora sarà tra {offset} minuti a {location}\n"
            "5 minutes\n10 minutes\n15 minutes\n"
        )
        issues = validate_entity(parsed)
        assert any(i.rule_name == "context_bleed" and i.severity == "error" for i in issues)


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


class TestPipeOutsideGroup:
    """OVOS-INTENT-1 §3.1 and §3.2: a pipe is a grammar token only inside a
    group.

    §3.2 reads "Parentheses enclose branches separated by the pipe |", and
    §3.3 makes "[x] exactly equivalent to the alternative group (x|)".
    Anywhere else §3.1 applies: "Any run of characters that is not a grammar
    token is literal text". The expander agrees, and answers
    ``expand("turn on|switch on the lights")`` with that one line, pipe and
    all, so the sample trains the engine on words no speaker says.

    The real lines are from ovos-skill-mark1-ctrl#76 (ca-ES) and
    ovos-skill-weather#271 (de-DE, es-ES).
    """

    def test_the_mark1_ctrl_line_is_an_error(self) -> None:
        parsed = IntentParser().parse_content(
            "enfosqueix|atenua una mica\nabaixa la brillantor\n")
        issues = validate_intent(parsed)
        hit = [i for i in issues if i.rule_name == "intent.pipe_outside_group"]
        assert len(hit) == 1
        assert hit[0].severity == "error"
        assert hit[0].line_number == 1

    def test_a_line_that_ends_in_a_pipe_is_an_error(self) -> None:
        # weather#271: a legal group earlier in the same line does not make
        # the trailing pipe legal.
        parsed = IntentParser().parse_content(
            "Se (espera|prevé) nieve en el pronóstico|\nva a nevar\n")
        issues = validate_intent(parsed)
        assert any(i.rule_name == "intent.pipe_outside_group" for i in issues)

    def test_a_pipe_inside_parentheses_is_grammar(self) -> None:
        parsed = IntentParser().parse_content(
            "(enfosqueix|atenua) una mica\nabaixa la brillantor\n")
        assert not [i for i in validate_intent(parsed)
                    if i.rule_name == "intent.pipe_outside_group"]

    def test_a_pipe_inside_brackets_is_grammar(self) -> None:
        # §3.3: [x] is exactly equivalent to (x|).
        parsed = IntentParser().parse_content(
            "how humid is it [right now|today]\nhow humid is it\n")
        assert not [i for i in validate_intent(parsed)
                    if i.rule_name == "intent.pipe_outside_group"]

    def test_a_dialog_line_is_an_error_too(self) -> None:
        # A dialog is expanded by the renderer, so the same reading applies.
        parsed = DialogParser().parse_content("bom dia|\nboa tarde\n")
        issues = validate_dialog(parsed)
        hit = [i for i in issues if i.rule_name == "dialog.pipe_outside_group"]
        assert len(hit) == 1
        assert hit[0].severity == "error"

    def test_a_nested_group_keeps_its_pipes(self) -> None:
        parsed = IntentParser().parse_content(
            "(turn (on|off)|switch (on|off)) the lights\nlights\n")
        assert not [i for i in validate_intent(parsed)
                    if i.rule_name == "intent.pipe_outside_group"]
