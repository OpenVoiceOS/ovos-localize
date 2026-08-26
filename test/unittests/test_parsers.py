"""Unit tests for locale file parsers."""

import json

from ovos_localize.parsers import get_parser
from ovos_localize.parsers.dialog import DialogParser
from ovos_localize.parsers.entity import EntityParser
from ovos_localize.parsers.intent import IntentParser
from ovos_localize.parsers.regex import RegexParser
from ovos_localize.parsers.settings_meta import SettingsMetaParser
from ovos_localize.parsers.skill_json import SkillJsonParser
from ovos_localize.parsers.value import ValueParser
from ovos_localize.parsers.vocab import VocabParser


class TestGetParser:
    """Tests for the get_parser() dispatch function."""

    def test_intent_by_extension(self) -> None:
        assert get_parser("hello.intent") is IntentParser

    def test_voc_by_extension(self) -> None:
        assert get_parser("weather.voc") is VocabParser

    def test_dialog_by_extension(self) -> None:
        assert get_parser("time.current.dialog") is DialogParser

    def test_entity_by_extension(self) -> None:
        assert get_parser("color.entity") is EntityParser

    def test_regex_by_extension(self) -> None:
        assert get_parser("location.rx") is RegexParser

    def test_value_by_extension(self) -> None:
        assert get_parser("timezone.value") is ValueParser

    def test_skill_json_by_name(self) -> None:
        assert get_parser("skill.json") is SkillJsonParser

    def test_settingsmeta_by_name(self) -> None:
        assert get_parser("settingsmeta.json") is SettingsMetaParser
        assert get_parser("settingsmeta.yml") is SettingsMetaParser

    def test_unknown_returns_none(self) -> None:
        assert get_parser("README.md") is None

    def test_path_with_directory(self) -> None:
        assert get_parser("locale/en-us/hello.intent") is IntentParser


class TestIntentParser:
    """Tests for .intent file parsing."""

    def test_basic_parse(self) -> None:
        content = "what time is it\nwhat time is it now\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        assert result.file_type == "intent"
        assert result.line_count == 2

    def test_slots_extracted(self) -> None:
        content = "what time is it in {location}\nset alarm for {time}\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        assert sorted(result.all_slots) == ["location", "time"]

    def test_alternatives_extracted(self) -> None:
        content = "play (some|any) music\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        assert result.content_lines[0].alternatives == [["some", "any"]]

    def test_comments_skipped(self) -> None:
        content = "# this is a comment\nhello world\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        assert result.line_count == 1

    def test_blank_lines_skipped(self) -> None:
        content = "hello world\n\ngoodbye world\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        assert result.line_count == 2

    def test_serialize_roundtrip(self) -> None:
        content = "what time is it\nwhat time is it now\n"
        parser = IntentParser()
        result = parser.parse_content(content)
        serialized = parser.serialize(result)
        assert "what time is it" in serialized
        assert "what time is it now" in serialized

    def test_diversity_high(self) -> None:
        lines_content = "\n".join([
            "what time is it",
            "tell me the current time",
            "do you know what hour it is",
            "can you check the clock",
            "what does the clock say",
        ])
        parser = IntentParser()
        result = parser.parse_content(lines_content)
        diversity = IntentParser.compute_diversity(result.lines)
        assert diversity > 0.5

    def test_diversity_low(self) -> None:
        lines_content = "\n".join([
            "what time is it",
            "what time is it now",
            "what time is it here",
            "what time is it there",
        ])
        parser = IntentParser()
        result = parser.parse_content(lines_content)
        diversity = IntentParser.compute_diversity(result.lines)
        assert diversity < 0.5


class TestVocabParser:
    """Tests for .voc file parsing."""

    def test_basic_parse(self) -> None:
        content = "weather\nforecast\n"
        parser = VocabParser()
        result = parser.parse_content(content)
        assert result.line_count == 2
        assert result.file_type == "voc"

    def test_word_count_metadata(self) -> None:
        content = "hello world how are you today\n"
        parser = VocabParser()
        result = parser.parse_content(content)
        assert result.content_lines[0].metadata["word_count"] == 6

    def test_alternatives(self) -> None:
        content = "hello (world|there)\n"
        parser = VocabParser()
        result = parser.parse_content(content)
        assert result.content_lines[0].alternatives == [["world", "there"]]


class TestDialogParser:
    """Tests for .dialog file parsing."""

    def test_basic_parse(self) -> None:
        content = "It is {time}\nThe time is {time}\n"
        parser = DialogParser()
        result = parser.parse_content(content)
        assert result.line_count == 2
        assert result.all_slots == ["time"]

    def test_multiple_variables(self) -> None:
        content = "The date is {date}, {num_days} from now\n"
        parser = DialogParser()
        result = parser.parse_content(content)
        assert sorted(result.all_slots) == ["date", "num_days"]

    def test_no_variables(self) -> None:
        content = "Hello world\nGoodbye\n"
        parser = DialogParser()
        result = parser.parse_content(content)
        assert result.all_slots == []


class TestEntityParser:
    """Tests for .entity file parsing."""

    def test_basic_parse(self) -> None:
        content = "red\nblue\ngreen\n"
        parser = EntityParser()
        result = parser.parse_content(content)
        assert result.line_count == 3

    def test_comments_filtered(self) -> None:
        content = "# colors\nred\nblue\n"
        parser = EntityParser()
        result = parser.parse_content(content)
        assert result.line_count == 2


class TestRegexParser:
    """Tests for .rx file parsing."""

    def test_named_groups_extracted(self) -> None:
        content = r"\b(at|in|for) (?P<Location>.*)" + "\n"
        parser = RegexParser()
        result = parser.parse_content(content)
        assert result.all_slots == ["Location"]

    def test_invalid_regex_error(self) -> None:
        content = "[invalid regex\n"
        parser = RegexParser()
        result = parser.parse_content(content)
        assert len(result.errors) > 0
        assert not result.content_lines[0].metadata["compiles"]

    def test_valid_regex_compiles(self) -> None:
        content = r"(?P<Time>\d{1,2}:\d{2})" + "\n"
        parser = RegexParser()
        result = parser.parse_content(content)
        assert result.content_lines[0].metadata["compiles"] is True


class TestValueParser:
    """Tests for .value file parsing."""

    def test_basic_parse(self) -> None:
        content = "China,Etc/GMT+8\nPacific time,US/Pacific-New\n"
        parser = ValueParser()
        result = parser.parse_content(content)
        assert result.line_count == 2
        line = result.content_lines[0]
        assert line.metadata["display"] == "China"
        assert line.metadata["system_value"] == "Etc/GMT+8"

    def test_invalid_format(self) -> None:
        content = "no comma here\n"
        parser = ValueParser()
        result = parser.parse_content(content)
        assert len(result.errors) > 0

    def test_serialize_preserves_values(self) -> None:
        content = "China,Etc/GMT+8\nPacific time,US/Pacific-New\n"
        parser = ValueParser()
        result = parser.parse_content(content)
        serialized = parser.serialize(result)
        assert "China,Etc/GMT+8" in serialized
        assert "Pacific time,US/Pacific-New" in serialized


class TestSkillJsonParser:
    """Tests for skill.json parsing."""

    def test_basic_parse(self) -> None:
        data = {
            "skill_id": "test-skill",
            "name": "Test Skill",
            "description": "A test",
            "examples": ["hello", "test"],
        }
        parser = SkillJsonParser()
        result = parser.parse_content(json.dumps(data))
        assert result.file_type == "skill.json"
        translatable = [
            ln for ln in result.lines if ln.metadata.get("translatable")
        ]
        assert len(translatable) >= 3  # name, description, 2 examples

    def test_invalid_json(self) -> None:
        parser = SkillJsonParser()
        result = parser.parse_content("{invalid}")
        assert len(result.errors) > 0

    def test_non_translatable_keys(self) -> None:
        data = {"skill_id": "test", "source": "https://github.com/test"}
        parser = SkillJsonParser()
        result = parser.parse_content(json.dumps(data))
        non_translatable = [
            ln for ln in result.lines if not ln.metadata.get("translatable")
        ]
        assert len(non_translatable) == 2


class TestSettingsMetaParser:
    """Tests for settingsmeta.json/yml parsing."""

    def test_basic_parse(self) -> None:
        data = {
            "skillMetadata": {
                "sections": [
                    {
                        "name": "General",
                        "fields": [
                            {"name": "Username", "label": "Your username", "type": "text"}
                        ],
                    }
                ]
            }
        }
        parser = SettingsMetaParser()
        result = parser.parse_content(json.dumps(data))
        translatable = [
            ln for ln in result.lines if ln.metadata.get("translatable")
        ]
        assert len(translatable) >= 2  # "General", "Username", "Your username"
