"""A dataset row is never one word repeated (T-4649).

`ovos-ocp-audio-plugin` shipped `tr-tr/Prev.voc` with one word 250 times, and
the row reached the published classification and translation datasets. The
predicate and all four generators that emit locale text are tested here.
"""

from typing import Any

from ovos_localize.bracket_expansion import MAX_WORD_REPEATS, is_repeated_word
from ovos_localize.datasets.classification import generate_intent_classification
from ovos_localize.datasets.response_pairs import generate_response_pairs
from ovos_localize.datasets.translation import generate_parallel_corpora
from ovos_localize.datasets.tts_corpus import generate_tts_corpus

SKILL_ID = "test-skill"

# The real line, shortened. tr-tr Prev.voc held 250 of these.
JUNK = " ".join(["önceki"] * 12)
GOOD = "önceki parça"


def _lang_data(entries: list[str]) -> dict:
    return {"entries": [{"text": t, "line": i + 1} for i, t in enumerate(entries)]}


def _make_skill(files: dict[str, Any]) -> dict:
    return {"id": SKILL_ID, "files": files}


class TestIsRepeatedWord:
    def test_the_real_junk_line_is_caught(self) -> None:
        assert is_repeated_word(" ".join(["oyun"] * 51))
        assert is_repeated_word(" ".join(["start"] * 99))
        assert is_repeated_word(" ".join(["önceki"] * 250))

    def test_a_real_phrase_is_left_alone(self) -> None:
        for text in ("önceki parça", "play the next song", "geçe", ""):
            assert not is_repeated_word(text)

    def test_three_repeats_are_left_alone(self) -> None:
        """A person does say "no no no"; the rule starts above three."""
        assert not is_repeated_word("no no no")
        assert is_repeated_word("no no no no")

    def test_the_threshold_is_the_named_constant(self) -> None:
        word = "a"
        assert not is_repeated_word(" ".join([word] * MAX_WORD_REPEATS))
        assert is_repeated_word(" ".join([word] * (MAX_WORD_REPEATS + 1)))

    def test_case_does_not_hide_a_repeat(self) -> None:
        """The dataset lowercases, but the predicate is used on raw text too."""
        assert is_repeated_word("Oyun oyun OYUN oyun oyun")

    def test_two_different_words_are_not_a_repeat(self) -> None:
        assert not is_repeated_word("oyun oyun oyun start")


class TestGeneratorsDropTheRow:
    def _skill(self) -> dict:
        return _make_skill({
            "Prev.voc": {
                "type": "voc",
                "langs": {
                    "en-US": _lang_data(["previous"]),
                    "tr-TR": _lang_data([GOOD, JUNK]),
                },
            },
        })

    def test_classification_drops_the_row(self) -> None:
        rows = list(generate_intent_classification(SKILL_ID, self._skill()))
        texts = {r["text"] for r in rows}
        assert GOOD in texts
        assert JUNK not in texts
        assert not any(is_repeated_word(r["text"]) for r in rows)

    def test_translation_drops_the_text_and_keeps_the_pair(self) -> None:
        rows = list(generate_parallel_corpora(SKILL_ID, self._skill()))
        assert rows, "the row must survive: only the bad text goes"
        row = next(r for r in rows if r["target_lang"] == "tr-TR")
        assert GOOD in row["target_texts"]
        assert JUNK not in row["target_texts"]
        assert row["base_texts"] == ["previous"]

    def test_tts_corpus_drops_the_row(self) -> None:
        skill = _make_skill({
            "prev.dialog": {
                "type": "dialog",
                "langs": {"tr-TR": _lang_data([GOOD, JUNK])},
            },
        })
        rows = list(generate_tts_corpus(SKILL_ID, skill))
        texts = {r["text"] for r in rows}
        assert GOOD in texts
        assert JUNK not in texts

    def test_response_pairs_drops_it_on_both_sides(self) -> None:
        skill = _make_skill({
            "prev.dialog": {
                "type": "dialog",
                "langs": {"tr-TR": _lang_data([GOOD, JUNK])},
            },
            "prev.intent": {
                "type": "intent",
                "context": {"triggers_dialog": ["prev"], "handler_method": "h"},
                "langs": {"tr-TR": _lang_data([GOOD, JUNK])},
            },
        })
        rows = list(generate_response_pairs(SKILL_ID, skill))
        assert rows
        for row in rows:
            assert not is_repeated_word(row["utterance"])
            for response in row["responses"]:
                assert not is_repeated_word(response)


class TestTheWholeTreeIsClean:
    def test_no_generator_emits_a_repeat_from_a_repeat_only_file(self) -> None:
        """A file whose only line is junk yields nothing, not an empty text."""
        skill = _make_skill({
            "Prev.voc": {
                "type": "voc",
                "langs": {
                    "en-US": _lang_data(["previous"]),
                    "tr-TR": _lang_data([JUNK]),
                },
            },
        })
        rows = list(generate_intent_classification(SKILL_ID, skill))
        assert [r["text"] for r in rows] == ["previous"]
        pairs = list(generate_parallel_corpora(SKILL_ID, skill))
        assert all(r["target_lang"] != "tr-TR" for r in pairs), (
            "a target language left with no text carries no pair"
        )
