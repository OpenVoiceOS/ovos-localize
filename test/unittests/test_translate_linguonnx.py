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
    _translate_literal,
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


def _stripping_translate_fn(text, s, t):
    """Mimics the real model: strips edge whitespace and uppercases the
    stripped core. translate_templated must never send un-stripped text or
    the group boundary loses its separating space (T-1986 review)."""
    return text.strip().upper()


def test_translate_templated_keeps_a_space_at_a_group_boundary():
    """Regression for the T-1986 review: joining pieces with "".join lost
    the space around a group when the model stripped its own edges, giving
    ``[A maioria]popular(filmes|...)`` instead of the correct spacing."""
    masked = "tell me about the (movie|film|flick) [0]"
    out = translate_templated(_stripping_translate_fn, masked, "en", "pt")
    assert out == "TELL ME ABOUT THE (MOVIE|FILM|FLICK) [0]"


def test_translate_templated_parses_a_nested_group():
    """Regression for the T-1986 review: the old TEMPLATE_RE matched only
    the innermost group, so the outer alternation's own '(' and '|' reached
    the model as literal text on a real moviemaster line."""
    out = translate_templated(_stripping_translate_fn, "(a|(b|c)) d", "en", "pt")
    assert out == "(A|(B|C)) D"


def test_translate_templated_splits_a_bracket_optional_alternation():
    """Regression for the T-1986 review: '[a|b]' went to the model whole as
    'a|b', the exact syntax-leak the '(|)' split was supposed to prevent."""
    out = translate_templated(_stripping_translate_fn, "[a|b] thing", "en", "pt")
    assert out == "[A|B] THING"


def test_translate_templated_recurses_into_a_bracket_holding_a_group():
    out = translate_templated(_stripping_translate_fn, "[(a|b)] thing", "en", "pt")
    assert out == "[(A|B)] THING"


def test_translate_templated_drops_a_line_with_a_lexical_duplicate():
    """Regression for the T-1986 review: 'movie' and 'film' both translate
    to pt 'filmes', so the split alone does not stop moviemaster#86's
    collapsed alternation -- a real duplicate after translation must drop
    the line."""

    def translate_fn(text, s, t):
        return {"movie": "filmes", "film": "filmes", "flick": "flicks"}.get(text, text)

    out = translate_templated(translate_fn, "(movie|film|flick)", "en", "pt")
    assert out is None


def test_translate_templated_keeps_distinct_alternatives():
    def translate_fn(text, s, t):
        return {"movie": "filme", "flick": "flicks"}.get(text, text)

    out = translate_templated(translate_fn, "(movie|flick)", "en", "pt")
    assert out == "(filme|flicks)"


def test_translate_line_drops_a_line_whose_group_collapses_to_a_duplicate():
    def translate_fn(text, s, t):
        return {"movie": "filmes", "film": "filmes", "flick": "flicks"}.get(text, text)

    out = translate_line(translate_fn, "tell me about the (movie|film|flick) {movie}", "en", "pt")
    assert out is None


def test_translate_templated_drops_a_case_only_duplicate():
    """Regression for the T-2015 review (finding A): the live es-ES route
    wrote (películas|Películas|flicks) -- a case-only duplicate the plain
    .strip() comparison missed."""

    def translate_fn(text, s, t):
        return {"movies": "películas", "films": "Películas", "flicks": "flicks"}.get(text, text)

    out = translate_templated(translate_fn, "(movies|films|flicks)", "en", "es")
    assert out is None


def test_translate_templated_drops_a_punctuation_only_duplicate():
    def translate_fn(text, s, t):
        return {"movies": "filmes.", "films": "filmes", "flicks": "flicks"}.get(text, text)

    out = translate_templated(translate_fn, "(movies|films|flicks)", "en", "pt")
    assert out is None


def test_translate_literal_strips_sentence_punctuation_the_source_never_had():
    """Regression for the T-2015 review (finding B): a piece translated
    alone out of sentence context picks up capitals and ¿¡.?! the fragment
    never asked for -- (búsqueda|Mira.) and (lista|¿Qué son?|buscar)."""

    def translate_fn(text, s, t):
        return {"search": "Mira.", "what are": "¿Qué son?"}.get(text, text.upper())

    assert _translate_literal(translate_fn, "search", "en", "es") == "mira"
    assert _translate_literal(translate_fn, "what are", "en", "es") == "qué son"


def test_translate_literal_keeps_punctuation_the_source_already_had():
    def translate_fn(text, s, t):
        return "¿Qué son?"

    # the source piece itself is a question, so the model's ¿...? is kept
    assert _translate_literal(translate_fn, "what are?", "en", "es") == "¿Qué son?"


def test_degenerate_reason_exempts_a_slot_only_line():
    """Regression for the T-2015 review (finding C): a slot-only line's
    mask round-trips unchanged, so it always looks 'identical to input'."""
    assert degenerate_reason("{query}", "{query}") is None


def test_degenerate_reason_exempts_a_bare_brand_word():
    assert degenerate_reason("spotify", "spotify") is None


def test_degenerate_reason_exempts_a_brand_only_group():
    assert degenerate_reason("(spotify|youtube)", "(spotify|youtube)") is None


def test_degenerate_reason_still_catches_a_non_brand_identical_word():
    assert degenerate_reason("hello", "hello") == "output identical to input"


def test_translate_templated_drops_an_unbalanced_group(caplog):
    """Regression for the T-2015 review (finding D, PLAUSIBLE): an
    unclosed '(' used to make the parser silently drop everything after
    it ('(a|(b|c) d' -> '(A|(B|C) )', losing ' d'); it must warn and drop
    the whole line instead."""

    def translate_fn(text, s, t):
        return text.upper()

    with caplog.at_level("WARNING"):
        out = translate_templated(translate_fn, "(a|(b|c) d", "en", "pt")
    assert out is None
    assert any("unbalanced" in r.message for r in caplog.records)


def test_translate_literal_keeps_a_german_noun_capital():
    """Regression for the T-2033 review (finding E): the live de-DE route
    wrote (filme|lieder) for (movies|songs) -- German writes every noun
    with a capital, and the decapitalization added for finding B removed
    it. The model's capital is kept for a noun-capitalizing target."""

    def translate_fn(text, s, t):
        return {"movies": "Filme", "songs": "Lieder"}.get(text, text)

    assert _translate_literal(translate_fn, "movies", "en", "de") == "Filme"
    assert _translate_literal(translate_fn, "movies", "en", "de-DE") == "Filme"
    assert translate_templated(translate_fn, "(movies|songs)", "en", "de-DE") == "(Filme|Lieder)"


def test_translate_literal_still_decapitalizes_a_non_noun_capitalizing_target():
    def translate_fn(text, s, t):
        return {"search": "Mira."}.get(text, text)

    assert _translate_literal(translate_fn, "search", "en", "es-ES") == "mira"


def test_translate_literal_changes_the_first_character_only():
    """A capital that is not at index 0 belongs to the word (a name), never
    to the sentence dressing, so it is kept on every target."""

    def translate_fn(text, s, t):
        return "Reproduce Spotify"

    assert _translate_literal(translate_fn, "play spotify", "en", "es") == "reproduce Spotify"


def test_translate_line_keeps_a_whole_sentence_dialog_line_untouched():
    """A .dialog line is a whole sentence: its source starts with a capital,
    so the decapitalization never applies to it on any target."""

    def translate_fn(text, s, t):
        return {"What is the weather": "Wie ist das Wetter",
                "The weather is nice": "Das Wetter ist schön"}.get(text, text)

    assert translate_line(translate_fn, "What is the weather", "en", "de-DE") == "Wie ist das Wetter"
    assert translate_line(translate_fn, "The weather is nice", "en", "de-DE") == "Das Wetter ist schön"


def test_translate_templated_keeps_an_optional_punctuation_group():
    """Regression for the T-2033 review (finding F): '(.|)' gave two empty
    dedupe keys at 777dad1 and the line was dropped as a duplicate."""

    def translate_fn(text, s, t):
        return text.upper()

    assert translate_templated(translate_fn, "(.|) x", "en", "pt") == "(.|) X"
    assert translate_templated(translate_fn, "x (?|!)", "en", "pt") == "X (?|!)"


def test_translate_templated_still_drops_a_real_empty_duplicate():
    def translate_fn(text, s, t):
        return text.upper()

    assert translate_templated(translate_fn, "(|) x", "en", "pt") is None


@pytest.mark.parametrize("line, stray", [("a) b (c|d)", ")"), ("(a|b)] c", "]"), ("x ] (y|z)", "]")])
def test_translate_templated_drops_a_stray_close_bracket(caplog, line, stray):
    """Regression for the T-2033 review (finding G): 'a) b (c|d)' shipped
    as 'A) B (C|D)' -- the stray close went to the model as text."""

    def translate_fn(text, s, t):
        return text.upper()

    with caplog.at_level("WARNING"):
        out = translate_templated(translate_fn, line, "en", "pt")
    assert out is None
    assert any("stray" in r.message and repr(stray) in r.message for r in caplog.records)


def test_translate_templated_keeps_a_mixed_nested_line_with_balanced_brackets():
    def translate_fn(text, s, t):
        return text.upper()

    assert translate_templated(translate_fn, "[(a|b) c] (d|[e])", "en", "pt") == "[(A|B) C] (D|[E])"


def test_translate_templated_never_sends_a_punctuation_only_alternative():
    """The real de route turns a lone '.' into a run of dots (T-2033 live
    probe); punctuation has nothing to translate and is copied as-is."""
    sent = []

    def translate_fn(text, s, t):
        sent.append(text)
        return text.upper()

    assert translate_templated(translate_fn, "try again (.|)", "en", "de") == "TRY AGAIN (.|)"
    assert sent == ["try again"]
