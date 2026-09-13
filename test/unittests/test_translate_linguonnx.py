import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from translate_linguonnx import (  # noqa: E402
    mask_placeholders,
    unmask_placeholders,
    degenerate_reason,
    translate_line,
    translate_lines,
    translate_templated,
    target_path,
    translate_tree,
)


class NoRouteError(Exception):
    pass


class FakeHop:
    def __init__(self, model_id, src, tgt):
        self.model_id, self.src, self.tgt = model_id, src, tgt


class FakeRoute:
    def __init__(self, hops):
        self.hops = hops


class DroppingTranslator:
    """Mimics the real linguonnx en->pt bug: a brace-delimited word is dropped."""

    def route(self, src, tgt):
        return FakeRoute([FakeHop("opus-mt-en-pt-int8", src, tgt)])

    def translate(self, text, src=None, tgt=None):
        # The real bug drops a bare brace-delimited slot; masked text no
        # longer contains one, so this only fires on an un-masked call.
        return text.replace("{city}", "")


class MunglingTranslator:
    """Mimics the real linguonnx en->de bug: a brace-delimited word is translated."""

    def route(self, src, tgt):
        return FakeRoute([FakeHop("opus-mt-en-de-int8", src, tgt)])

    def translate(self, text, src=None, tgt=None):
        return text.replace("{time}", "{Zeit}")


class NoRouteTranslator:
    def route(self, src, tgt):
        raise NoRouteError(f"no route {src}->{tgt}")

    def translate(self, text, src=None, tgt=None):
        raise AssertionError("translate should never be called without a route")


class EchoTranslator:
    """Round-trips every mask token unchanged, for shape tests."""

    def route(self, src, tgt):
        return FakeRoute([FakeHop("echo", src, tgt)])

    def translate(self, text, src=None, tgt=None):
        return text.upper()


def test_mask_then_unmask_is_identity():
    line = "what is the weather in {city} at {time}"
    masked, placeholders = mask_placeholders(line)
    assert "{city}" not in masked and "{time}" not in masked
    assert unmask_placeholders(masked, placeholders) == line


def test_mask_placeholders_orders_by_first_occurrence():
    masked, placeholders = mask_placeholders("{a} then {b} then {a}")
    assert placeholders == ["{a}", "{b}", "{a}"]


def test_no_placeholders_round_trips():
    masked, placeholders = mask_placeholders("hello world")
    assert placeholders == []
    assert unmask_placeholders(masked, placeholders) == "hello world"


def test_blank_line_is_not_sent_to_the_model():
    calls = []

    def translate_fn(text, s, t):
        calls.append(text)
        return text

    assert translate_line(translate_fn, "", "en", "pt") == ""
    assert translate_line(translate_fn, "   ", "en", "pt") == "   "
    assert calls == []


def test_placeholder_survives_a_translator_that_drops_it():
    """The linguonnx en->pt bug: {city} alone is dropped. Masked, it survives."""
    tx = DroppingTranslator()

    def translate_fn(text, s, t):
        return tx.translate(text, src=s, tgt=t)

    out = translate_line(translate_fn, "weather in {city}", "en", "pt")
    assert "{city}" in out


def test_placeholder_survives_a_translator_that_translates_it():
    """The linguonnx en->de bug: {time} becomes {Zeit}. Masked, it survives."""
    tx = MunglingTranslator()

    def translate_fn(text, s, t):
        return tx.translate(text, src=s, tgt=t)

    out = translate_line(translate_fn, "set a timer for {time}", "en", "de")
    assert "{time}" in out
    assert "{Zeit}" not in out


def test_translate_lines_preserves_line_count_when_every_mask_survives():
    def translate_fn(text, s, t):
        return text.upper()

    lines = ["hello", "", "world with {slot}"]
    out = translate_lines(translate_fn, lines, "en", "pt")
    assert len(out) == len(lines)


def test_translate_lines_drops_only_the_line_whose_mask_did_not_survive():
    def translate_fn(text, s, t):
        # [0] never comes back; anything without a placeholder is untouched.
        return text.replace("[0]", "")

    lines = ["plain line", "has a {slot} in it", "another plain line"]
    out = translate_lines(translate_fn, lines, "en", "pt")
    assert out == ["plain line", "another plain line"]


def test_target_path_replaces_only_the_locale_segment():
    src_dir = Path("/skill/locale/en-US")
    path = src_dir / "intents" / "Hello.intent"
    dest = target_path(src_dir, Path("/out"), path, "pt-PT")
    assert dest == Path("/out/pt-PT/intents/Hello.intent")


def test_translate_tree_reports_and_skips_a_route_less_locale(tmp_path):
    src = tmp_path / "en-US"
    src.mkdir()
    (src / "a.intent").write_text("hello\n")
    out = tmp_path / "out"

    written = translate_tree(NoRouteTranslator(), src, out, "xx-XX", "en", "xx")
    assert written is None
    assert not out.exists()


def test_translate_tree_writes_every_suffix_and_keeps_line_counts(tmp_path):
    src = tmp_path / "en-US"
    src.mkdir()
    (src / "greet.intent").write_text("hi\nhello there\n")
    (src / "reply.dialog").write_text("thanks\n")
    (src / "kw.voc").write_text("word\n")
    (src / "ent.entity").write_text("thing\n")
    (src / "skip.json").write_text("{}")  # not a translatable resource, ignored
    out = tmp_path / "out"

    written = translate_tree(EchoTranslator(), src, out, "de-DE", "en", "de")
    assert written is not None
    assert len(written) == 4  # skip.json excluded

    got = (out / "de-DE" / "greet.intent").read_text().splitlines()
    want = (src / "greet.intent").read_text().splitlines()
    assert len(got) == len(want)
    assert got == [line.upper() for line in want]


def test_translate_tree_drops_a_line_whose_mask_did_not_survive(tmp_path):
    src = tmp_path / "en-US"
    src.mkdir()
    (src / "weather.dialog").write_text(
        "weather in {city} at {time}\nhello there\n")
    out = tmp_path / "out"

    class DropsFirstMaskOnly:
        """[0] never comes back; [1] always does -- one bad line, one good one."""

        def route(self, s, t):
            return FakeRoute([FakeHop("opus-mt-en-pt-int8", s, t)])

        def translate(self, text, src=None, tgt=None):
            return text.replace("[0]", "").upper()

    translate_tree(DropsFirstMaskOnly(), src, out, "pt-PT", "en", "pt")
    result = (out / "pt-PT" / "weather.dialog").read_text().splitlines()
    assert result == ["HELLO THERE"]  # the {city}/{time} line was dropped


def test_translate_tree_skips_a_file_with_no_surviving_line(tmp_path):
    src = tmp_path / "en-US"
    src.mkdir()
    (src / "spell.word.dialog").write_text("{word} is spelled {letters}\n")
    out = tmp_path / "out"

    class DropsEveryMask:
        def route(self, s, t):
            return FakeRoute([FakeHop("nos-coda-en-gl-int8", s, t)])

        def translate(self, text, src=None, tgt=None):
            return "unrelated text with no mask left"

    written = translate_tree(DropsEveryMask(), src, out, "gl-ES", "en", "gl")
    assert written == []
    assert not (out / "gl-ES" / "spell.word.dialog").exists()


def test_translate_templated_splits_alternatives_and_optional_words():
    def translate_fn(text, s, t):
        return text.upper()

    masked = "the (movie|film|flick) is playing [tonight]"
    out = translate_templated(translate_fn, masked, "en", "pt")
    assert out == "THE (MOVIE|FILM|FLICK) IS PLAYING [TONIGHT]"


def test_translate_templated_leaves_a_mask_token_in_the_literal_run():
    """A ``[0]`` mask token is a bracket of digits, never a template group."""

    def translate_fn(text, s, t):
        return text  # identity; a group match would rewrite it

    masked = "info about [0] the (movie|film)"
    out = translate_templated(translate_fn, masked, "en", "pt")
    assert "[0]" in out
    assert "(movie|film)" in out


def test_translate_line_keeps_each_alternative_distinct_on_a_real_intent_line():
    """Regression for moviemaster#86 ``(irudiak|irudiak)`` and wallpapers#95
    ``filme-filme-filme``: a model that collapses distinct alternatives
    glued together with '|' into copies of one of them must not get the
    chance to, because each alternative now translates alone."""

    class DuplicatingTranslator:
        def translate(self, text, s, t):
            if "|" in text:
                first = text.split("|")[0]
                return "|".join([first] * (text.count("|") + 1))
            return text.upper()

    tx = DuplicatingTranslator()

    def translate_fn(text, s, t):
        return tx.translate(text, s, t)

    # a real en-US line from ovos-skill-moviemaster's movie.intent
    line = "tell me about the (movie|film|flick) {movie}"
    out = translate_line(translate_fn, line, "en", "pt")
    assert out == "TELL ME ABOUT THE (MOVIE|FILM|FLICK) {movie}"


def test_degenerate_reason_none_for_a_clean_translation():
    assert degenerate_reason("hello", "bonjour") is None


def test_degenerate_reason_catches_a_comma_separated_repetition_loop():
    """Regression for T-1665: pl-PL "hello"/"hello there"/"hey" all
    degenerated into "Cześć, cześć, cześć..." on the int8 model."""
    assert degenerate_reason("hello", "Cześć, cześć, cześć") == \
        "token repeated 3+ times in a row"


def test_degenerate_reason_catches_a_space_separated_repetition_loop():
    """Regression for T-1665: fa-IR "hey there" -> "آه آه آه آه آه"."""
    assert degenerate_reason("hey there", "آه آه آه آه آه") == \
        "token repeated 3+ times in a row"


def test_degenerate_reason_catches_a_single_stop_word():
    """Regression for T-1664: fa-IR "yo" -> "من" (the pronoun I/me)."""
    assert degenerate_reason("yo", "من") == "output is a single stop-word"


def test_degenerate_reason_catches_output_identical_to_input():
    assert degenerate_reason("hello", "hello") == "output identical to input"


def test_degenerate_reason_ignores_a_shared_word_on_a_longer_line():
    """Identical-output and single-stop-word only fire on a short bare-word
    original; a longer line keeping one shared word (a name, a slot) is not
    this defect."""
    assert degenerate_reason("weather in {city}", "weather in {city}") is None


def test_degenerate_reason_catches_an_oversized_output():
    assert degenerate_reason("hello", "one two three four five six") == \
        "output more than 3x longer than input"


def test_translate_line_drops_a_repetition_loop():
    def translate_fn(text, s, t):
        return "cześć, cześć, cześć"

    assert translate_line(translate_fn, "hello", "en", "pl") is None


def test_translate_lines_reports_the_drop_reason(caplog):
    def translate_fn(text, s, t):
        return "cześć, cześć, cześć"

    with caplog.at_level("WARNING"):
        out = translate_lines(translate_fn, ["hello"], "en", "pl")
    assert out == []
    assert any("token repeated 3+ times" in r.message for r in caplog.records)
