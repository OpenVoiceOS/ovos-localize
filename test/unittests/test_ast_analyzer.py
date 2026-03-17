"""Unit tests for the AST-based skill analyzer."""

import pytest

from ovos_localize.analyzers.ast_analyzer import SkillAnalyzer, SkillAnalysis


class TestSkillAnalyzer:
    """Tests for SkillAnalyzer."""

    def setup_method(self) -> None:
        """Create analyzer instance."""
        self.analyzer = SkillAnalyzer()

    def test_padatious_intent_handler(self) -> None:
        """Detect @intent_handler('file.intent') pattern."""
        source = '''
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills.ovos import OVOSSkill

class TestSkill(OVOSSkill):
    @intent_handler("hello.intent")
    def handle_hello(self, message):
        self.speak_dialog("hello.world")
'''
        result = self.analyzer.analyze_source(source)
        assert result.skill_class_name == "TestSkill"
        assert len(result.intent_handlers) == 1
        handler = result.intent_handlers[0]
        assert handler.intent_type == "padatious"
        assert handler.intent_file == "hello.intent"
        assert handler.method_name == "handle_hello"

    def test_adapt_intent_builder(self) -> None:
        """Detect IntentBuilder().require().optionally() pattern."""
        source = '''
from adapt.intent import IntentBuilder
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills.ovos import OVOSSkill

class WeatherSkill(OVOSSkill):
    @intent_handler(IntentBuilder("WeatherIntent").require("WeatherKeyword").optionally("Location"))
    def handle_weather(self, message):
        self.speak_dialog("weather", {"temp": "72"})
'''
        result = self.analyzer.analyze_source(source)
        assert len(result.intent_handlers) == 1
        handler = result.intent_handlers[0]
        assert handler.intent_type == "adapt"
        assert handler.builder_name == "WeatherIntent"
        assert "WeatherKeyword" in handler.required_keywords
        assert "Location" in handler.optional_keywords

    def test_speak_dialog_variables(self) -> None:
        """Extract dialog variable names from speak_dialog calls."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class TimeSkill(OVOSSkill):
    def handle_time(self, message):
        self.speak_dialog("time.current", {"time": now, "location": loc})
'''
        result = self.analyzer.analyze_source(source)
        assert len(result.dialog_calls) == 1
        call = result.dialog_calls[0]
        assert call.dialog_name == "time.current"
        assert sorted(call.variables) == ["location", "time"]

    def test_get_response_detected(self) -> None:
        """Detect self.get_response() calls."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class AlarmSkill(OVOSSkill):
    def handle_alarm(self, message):
        response = self.get_response("alarm_ask_time")
'''
        result = self.analyzer.analyze_source(source)
        assert len(result.response_calls) == 1
        assert result.response_calls[0].dialog_name == "alarm_ask_time"
        assert result.response_calls[0].call_type == "get_response"

    def test_ask_yesno_detected(self) -> None:
        """Detect self.ask_yesno() calls."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class ConfirmSkill(OVOSSkill):
    def handle_confirm(self, message):
        if self.ask_yesno("are_you_sure") == "yes":
            pass
'''
        result = self.analyzer.analyze_source(source)
        assert len(result.response_calls) == 1
        assert result.response_calls[0].call_type == "ask_yesno"

    def test_intent_file_to_handler_index(self) -> None:
        """Verify intent_file_to_handler index is built."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler("greetings.intent")
    def handle_greet(self, message):
        pass
'''
        result = self.analyzer.analyze_source(source)
        assert "greetings.intent" in result.intent_file_to_handler

    def test_voc_to_intents_index(self) -> None:
        """Verify voc_to_intents index for Adapt keywords."""
        source = '''
from adapt.intent import IntentBuilder
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler(IntentBuilder("TestIntent").require("TestKeyword").require("ActionKeyword"))
    def handle_test(self, message):
        pass
'''
        result = self.analyzer.analyze_source(source)
        assert "TestKeyword" in result.voc_to_intents
        assert "ActionKeyword" in result.voc_to_intents

    def test_dialog_to_callers_index(self) -> None:
        """Verify dialog_to_callers index."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class MySkill(OVOSSkill):
    def handle_a(self, message):
        self.speak_dialog("shared.dialog")
    def handle_b(self, message):
        self.speak_dialog("shared.dialog")
'''
        result = self.analyzer.analyze_source(source)
        callers = result.dialog_to_callers.get("shared.dialog", [])
        assert "handle_a" in callers
        assert "handle_b" in callers

    def test_voc_blacklist_extracted(self) -> None:
        """Extract voc_blacklist from intent_handler kwargs."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler("search.intent", voc_blacklist=["Weather", "Help"])
    def handle_search(self, message):
        pass
'''
        result = self.analyzer.analyze_source(source)
        handler = result.intent_handlers[0]
        assert handler.voc_blacklist == ["Weather", "Help"]

    def test_non_skill_class_ignored(self) -> None:
        """Classes not inheriting from *Skill should be ignored."""
        source = '''
class NotASkill:
    def handle_something(self, message):
        self.speak_dialog("test")
'''
        result = self.analyzer.analyze_source(source)
        assert result.skill_class_name == ""
        assert len(result.dialog_calls) == 0

    def test_syntax_error_returns_empty(self) -> None:
        """Gracefully handle syntax errors."""
        result = self.analyzer.analyze_source("def broken(:")
        assert result.skill_class_name == ""

    def test_adapt_with_build(self) -> None:
        """Handle IntentBuilder chains ending with .build()."""
        source = '''
from adapt.intent import IntentBuilder
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler(IntentBuilder("TestIntent").require("Keyword").build())
    def handle_test(self, message):
        pass
'''
        result = self.analyzer.analyze_source(source)
        assert len(result.intent_handlers) == 1
        assert result.intent_handlers[0].builder_name == "TestIntent"

    def test_speak_dialog_with_data_kwarg(self) -> None:
        """Handle speak_dialog(key, data={...}) keyword form."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class MySkill(OVOSSkill):
    def handle_test(self, message):
        self.speak_dialog("test", data={"name": value})
'''
        result = self.analyzer.analyze_source(source)
        assert result.dialog_calls[0].variables == ["name"]
