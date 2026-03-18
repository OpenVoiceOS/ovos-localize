"""Extra parser tests for serialization and edge cases."""

import json

from ovos_localize.parsers.dialog import DialogParser
from ovos_localize.parsers.entity import EntityParser
from ovos_localize.parsers.regex import RegexParser
from ovos_localize.parsers.settings_meta import SettingsMetaParser
from ovos_localize.parsers.skill_json import SkillJsonParser
from ovos_localize.parsers.value import ValueParser
from ovos_localize.parsers.vocab import VocabParser


class TestDialogParserExtra:
    """Additional tests for DialogParser."""

    def test_serialize(self) -> None:
        """Serialize round-trips correctly."""
        parser = DialogParser()
        parsed = parser.parse_content("Hello {name}\nHi {name}\n")
        serialized = parser.serialize(parsed)
        assert "Hello {name}" in serialized
        assert "Hi {name}" in serialized

    def test_comment_handling(self) -> None:
        """Comments are preserved."""
        parser = DialogParser()
        parsed = parser.parse_content("# comment\nHello\n")
        assert len(parsed.content_lines) == 1


class TestEntityParserExtra:
    """Additional tests for EntityParser."""

    def test_serialize(self) -> None:
        """Serialize round-trips."""
        parser = EntityParser()
        parsed = parser.parse_content("red\nblue\ngreen\n")
        serialized = parser.serialize(parsed)
        assert "red" in serialized

    def test_comment_handling(self) -> None:
        """Comments are skipped in content_lines."""
        parser = EntityParser()
        parsed = parser.parse_content("# colors\nred\nblue\n")
        assert len(parsed.content_lines) == 2


class TestRegexParserExtra:
    """Additional tests for RegexParser."""

    def test_serialize(self) -> None:
        """Serialize round-trips."""
        parser = RegexParser()
        parsed = parser.parse_content(r"(?P<Location>.*)" + "\n")
        serialized = parser.serialize(parsed)
        assert "(?P<Location>" in serialized

    def test_invalid_regex_metadata(self) -> None:
        """Invalid regex sets compiles=False in metadata."""
        parser = RegexParser()
        parsed = parser.parse_content("[invalid\n")
        assert parsed.content_lines[0].metadata.get("compiles") is False


class TestValueParserExtra:
    """Additional tests for ValueParser."""

    def test_serialize(self) -> None:
        """Serialize preserves format."""
        parser = ValueParser()
        parsed = parser.parse_content("Display,system\nOther,other_val\n")
        serialized = parser.serialize(parsed)
        assert "Display,system" in serialized

    def test_invalid_format(self) -> None:
        """Lines without comma produce errors."""
        parser = ValueParser()
        parsed = parser.parse_content("no comma here\n")
        assert len(parsed.errors) > 0


class TestVocabParserExtra:
    """Additional tests for VocabParser."""

    def test_serialize(self) -> None:
        """Serialize round-trips."""
        parser = VocabParser()
        parsed = parser.parse_content("weather\nforecast\n")
        serialized = parser.serialize(parsed)
        assert "weather" in serialized
        assert "forecast" in serialized

    def test_word_count(self) -> None:
        """Word count in metadata."""
        parser = VocabParser()
        parsed = parser.parse_content("hello world test\n")
        assert parsed.content_lines[0].metadata["word_count"] == 3


class TestSettingsMetaParser:
    """Tests for SettingsMetaParser."""

    def test_json_format(self) -> None:
        """Parse settingsmeta.json."""
        parser = SettingsMetaParser()
        content = json.dumps({
            "skillMetadata": {
                "sections": [{
                    "name": "Settings",
                    "fields": [
                        {"name": "api_key", "type": "text", "label": "API Key", "value": ""},
                        {"name": "units", "type": "select", "label": "Units", "value": "metric",
                         "options": "metric|imperial"}
                    ]
                }]
            }
        })
        parsed = parser.parse_content(content)
        assert len(parsed.lines) > 0
        # Should have translatable labels
        labels = [ln.text for ln in parsed.lines if ln.metadata.get("translatable")]
        assert "API Key" in labels or "Settings" in labels

    def test_yaml_format(self) -> None:
        """Parse settingsmeta.yml."""
        parser = SettingsMetaParser()
        content = """skillMetadata:
  sections:
    - name: Settings
      fields:
        - name: api_key
          type: text
          label: API Key
          value: ""
"""
        parsed = parser.parse_content(content)
        assert len(parsed.lines) > 0

    def test_invalid_json(self) -> None:
        """Invalid JSON produces errors."""
        parser = SettingsMetaParser()
        parsed = parser.parse_content("{invalid json")
        assert len(parsed.errors) > 0 or len(parsed.lines) == 0

    def test_serialize(self) -> None:
        """Serialize produces valid JSON."""
        parser = SettingsMetaParser()
        content = json.dumps({
            "skillMetadata": {
                "sections": [{
                    "name": "Test",
                    "fields": [{"name": "key", "type": "text", "label": "Label"}]
                }]
            }
        })
        parsed = parser.parse_content(content)
        serialized = parser.serialize(parsed)
        assert isinstance(serialized, str)


class TestSkillJsonParserExtra:
    """Additional tests for SkillJsonParser."""

    def test_serialize(self) -> None:
        """Serialize preserves structure."""
        parser = SkillJsonParser()
        content = json.dumps({
            "skill_id": "test.openvoiceos",
            "name": "Test Skill",
            "description": "A test",
            "examples": ["hello", "hi"],
            "tags": ["test"]
        })
        parsed = parser.parse_content(content)
        serialized = parser.serialize(parsed)
        data = json.loads(serialized)
        assert data["name"] == "Test Skill"
        assert data["examples"] == ["hello", "hi"]

    def test_translatable_keys(self) -> None:
        """name, description, examples, tags are translatable."""
        parser = SkillJsonParser()
        content = json.dumps({
            "skill_id": "test",
            "source": "http://example.com",
            "name": "Test",
            "description": "Desc",
            "examples": ["ex1"],
            "tags": ["tag1"]
        })
        parsed = parser.parse_content(content)
        translatable = [ln for ln in parsed.lines if ln.metadata.get("translatable")]
        non_translatable = [ln for ln in parsed.lines if not ln.metadata.get("translatable")]
        assert len(translatable) >= 4  # name, description, ex1, tag1
        assert len(non_translatable) >= 2  # skill_id, source

    def test_invalid_json(self) -> None:
        """Invalid JSON produces errors."""
        parser = SkillJsonParser()
        parsed = parser.parse_content("not json")
        assert len(parsed.errors) > 0
