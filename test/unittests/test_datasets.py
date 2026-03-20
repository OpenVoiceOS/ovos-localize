"""Unit tests for the four new ML dataset generators."""

from typing import Any, Dict, List

import pytest

from ovos_localize.datasets.slot_filling import generate_slot_filling
from ovos_localize.datasets.response_pairs import generate_response_pairs
from ovos_localize.datasets.tts_corpus import generate_tts_corpus
from ovos_localize.datasets.skill_metadata import generate_skill_metadata


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SKILL_ID = "test-skill"


def _make_skill(files: Dict[str, Any]) -> dict:
    return {"id": SKILL_ID, "files": files}


def _lang_data(entries: List[str]) -> dict:
    return {"entries": [{"text": t, "line": i + 1} for i, t in enumerate(entries)]}


# ---------------------------------------------------------------------------
# generate_slot_filling
# ---------------------------------------------------------------------------

class TestSlotFilling:
    def _skill(self) -> dict:
        return _make_skill({
            "launch.intent": {
                "type": "intent",
                "langs": {
                    "en-US": _lang_data(["open {application}", "launch {application}", "no slots here"]),
                    "fr-FR": _lang_data(["ouvrir {application}"]),
                },
            },
            "application.entity": {
                "type": "entity",
                "langs": {
                    "en-US": _lang_data(["firefox", "chrome"]),
                    "fr-FR": _lang_data(["firefox"]),
                },
            },
        })

    def test_yields_slot_records(self) -> None:
        records = list(generate_slot_filling(SKILL_ID, self._skill()))
        assert records

    def test_only_slotted_intents(self) -> None:
        records = list(generate_slot_filling(SKILL_ID, self._skill()))
        texts = [r["template"] for r in records]
        assert "no slots here" not in texts

    def test_slot_name_extracted(self) -> None:
        records = list(generate_slot_filling(SKILL_ID, self._skill()))
        en = [r for r in records if r["lang"] == "en-US"]
        assert all("application" in r["slots"] for r in en)

    def test_entity_values_populated(self) -> None:
        records = list(generate_slot_filling(SKILL_ID, self._skill()))
        en = next(r for r in records if r["lang"] == "en-US")
        assert set(en["entity_values"]["application"]) == {"firefox", "chrome"}

    def test_missing_entity_file_empty_values(self) -> None:
        skill = _make_skill({
            "find.intent": {
                "type": "intent",
                "langs": {"en-US": _lang_data(["find {query}"])},
            }
        })
        records = list(generate_slot_filling(SKILL_ID, skill))
        assert records[0]["entity_values"]["query"] == []

    def test_deduplication(self) -> None:
        skill = _make_skill({
            "test.intent": {
                "type": "intent",
                "langs": {"en-US": _lang_data(["open {app}", "open {app}"])},
            }
        })
        records = list(generate_slot_filling(SKILL_ID, skill))
        assert len(records) == 1

    def test_required_keys(self) -> None:
        records = list(generate_slot_filling(SKILL_ID, self._skill()))
        for r in records:
            assert {"lang", "skill", "intent", "template", "slots", "entity_values"} <= r.keys()

    def test_skips_voc_files(self) -> None:
        skill = _make_skill({
            "keywords.voc": {
                "type": "voc",
                "langs": {"en-US": _lang_data(["{something} here"])},
            }
        })
        records = list(generate_slot_filling(SKILL_ID, skill))
        assert records == []


# ---------------------------------------------------------------------------
# generate_response_pairs
# ---------------------------------------------------------------------------

class TestResponsePairs:
    def _skill(self) -> dict:
        return _make_skill({
            "Greetings.intent": {
                "type": "intent",
                "context": {
                    "triggers_dialog": ["hello"],
                    "handler_method": "handle_greetings",
                },
                "langs": {
                    "en-US": _lang_data(["hello", "hi there"]),
                    "fr-FR": _lang_data(["bonjour"]),
                },
            },
            "hello.dialog": {
                "type": "dialog",
                "langs": {
                    "en-US": _lang_data(["Hello!", "Hey!"]),
                    "fr-FR": _lang_data(["Bonjour!"]),
                },
            },
        })

    def test_yields_records(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        assert records

    def test_utterance_and_responses_present(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        en = [r for r in records if r["lang"] == "en-US"]
        assert all(r["responses"] for r in en)
        assert {r["utterance"] for r in en} == {"hello", "hi there"}

    def test_responses_match_dialog(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        en = next(r for r in records if r["lang"] == "en-US")
        assert set(en["responses"]) == {"hello!", "hey!"}

    def test_skips_intent_without_triggers_dialog(self) -> None:
        skill = _make_skill({
            "Goodbye.intent": {
                "type": "intent",
                "context": {"triggers_dialog": [], "handler_method": "handle_goodbye"},
                "langs": {"en-US": _lang_data(["bye"])},
            }
        })
        assert list(generate_response_pairs(SKILL_ID, skill)) == []

    def test_skips_lang_with_no_dialog_translation(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        langs = {r["lang"] for r in records}
        # fr-FR has a dialog translation — both should appear
        assert "en-US" in langs
        assert "fr-FR" in langs

    def test_handler_name_propagated(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        assert all(r["handler"] == "handle_greetings" for r in records)

    def test_required_keys(self) -> None:
        records = list(generate_response_pairs(SKILL_ID, self._skill()))
        for r in records:
            assert {"lang", "skill", "intent", "handler", "utterance", "responses"} <= r.keys()

    def test_deduplication(self) -> None:
        skill = _make_skill({
            "Test.intent": {
                "type": "intent",
                "context": {"triggers_dialog": ["hi"], "handler_method": "h"},
                "langs": {"en-US": _lang_data(["hello", "hello"])},
            },
            "hi.dialog": {
                "type": "dialog",
                "langs": {"en-US": _lang_data(["hi"])},
            },
        })
        records = list(generate_response_pairs(SKILL_ID, skill))
        assert len(records) == 1


# ---------------------------------------------------------------------------
# generate_tts_corpus
# ---------------------------------------------------------------------------

class TestTtsCorpus:
    def _skill(self) -> dict:
        return _make_skill({
            "hello.dialog": {
                "type": "dialog",
                "langs": {
                    "en-US": _lang_data(["Hello!", "Hello!", "Hey there!"]),
                    "fr-FR": _lang_data(["Bonjour!"]),
                },
            },
            "Greetings.intent": {
                "type": "intent",
                "langs": {"en-US": _lang_data(["hello"])},
            },
        })

    def test_yields_records(self) -> None:
        records = list(generate_tts_corpus(SKILL_ID, self._skill()))
        assert records

    def test_only_dialog_files(self) -> None:
        records = list(generate_tts_corpus(SKILL_ID, self._skill()))
        assert all(r["dialog"].endswith(".dialog") for r in records)

    def test_deduplication(self) -> None:
        records = list(generate_tts_corpus(SKILL_ID, self._skill()))
        en_texts = [r["text"] for r in records if r["lang"] == "en-US"]
        assert len(en_texts) == len(set(en_texts))

    def test_template_expansion(self) -> None:
        skill = _make_skill({
            "test.dialog": {
                "type": "dialog",
                "langs": {"en-US": _lang_data(["(yes|no)"])},
            }
        })
        records = list(generate_tts_corpus(SKILL_ID, skill))
        texts = {r["text"] for r in records if r["lang"] == "en-US"}
        assert texts == {"yes", "no"}

    def test_required_keys(self) -> None:
        records = list(generate_tts_corpus(SKILL_ID, self._skill()))
        for r in records:
            assert {"lang", "skill", "dialog", "text"} <= r.keys()

    def test_skips_comment_lines(self) -> None:
        skill = _make_skill({
            "test.dialog": {
                "type": "dialog",
                "langs": {"en-US": _lang_data(["# comment", "hello"])},
            }
        })
        records = list(generate_tts_corpus(SKILL_ID, skill))
        assert all(not r["text"].startswith("#") for r in records)


# ---------------------------------------------------------------------------
# generate_skill_metadata
# ---------------------------------------------------------------------------

class TestSkillMetadata:
    def _skill(self) -> dict:
        return _make_skill({
            "skill.json": {
                "type": "skill.json",
                "langs": {
                    "en-US": {
                        "entries": [
                            {"key": "name", "text": "Hello World"},
                            {"key": "description", "text": "A demo skill"},
                            {"key": "examples", "text": "Say hello\nHow are you"},
                            {"key": "tags", "text": "demo, tutorial"},
                        ]
                    },
                    "fr-FR": {
                        "entries": [
                            {"key": "name", "text": "Bonjour Monde"},
                            {"key": "description", "text": "Une démo"},
                            {"key": "examples", "text": "Dis bonjour"},
                            {"key": "tags", "text": "démo"},
                        ]
                    },
                    "incomplete": {
                        "entries": [
                            {"key": "name", "text": "Only Name"},
                            # missing description — should be skipped
                        ]
                    },
                },
            }
        })

    def test_yields_records(self) -> None:
        records = list(generate_skill_metadata(SKILL_ID, self._skill()))
        assert records

    def test_skips_incomplete_entries(self) -> None:
        records = list(generate_skill_metadata(SKILL_ID, self._skill()))
        langs = {r["lang"] for r in records}
        assert "incomplete" not in langs

    def test_examples_split_to_list(self) -> None:
        records = list(generate_skill_metadata(SKILL_ID, self._skill()))
        en = next(r for r in records if r["lang"] == "en-US")
        assert en["examples"] == ["Say hello", "How are you"]

    def test_tags_split_to_list(self) -> None:
        records = list(generate_skill_metadata(SKILL_ID, self._skill()))
        en = next(r for r in records if r["lang"] == "en-US")
        assert en["tags"] == ["demo", "tutorial"]

    def test_required_keys(self) -> None:
        records = list(generate_skill_metadata(SKILL_ID, self._skill()))
        for r in records:
            assert {"lang", "skill", "name", "description", "examples", "tags"} <= r.keys()

    def test_non_skill_json_skipped(self) -> None:
        skill = _make_skill({
            "hello.dialog": {
                "type": "dialog",
                "langs": {"en-US": _lang_data(["hello"])},
            }
        })
        assert list(generate_skill_metadata(SKILL_ID, skill)) == []
