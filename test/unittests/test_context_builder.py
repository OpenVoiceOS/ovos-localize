"""Unit tests for the context card builder."""


from ovos_localize.analyzers.ast_analyzer import SkillAnalyzer
from ovos_localize.analyzers.context_builder import build_context_card
from ovos_localize.enums import FileType
from ovos_localize.sync.github import ScannedFile


def _make_scanned(
    base_name: str, file_type: FileType, content: str = "", lang: str = "en-us"
) -> ScannedFile:
    """Helper to create a ScannedFile with parsed content."""
    from ovos_localize.parsers import get_parser
    ext_map = {
        FileType.INTENT: ".intent",
        FileType.VOCAB: ".voc",
        FileType.DIALOG: ".dialog",
        FileType.ENTITY: ".entity",
        FileType.REGEX: ".rx",
    }
    ext = ext_map.get(file_type, "")
    filename = f"{base_name}{ext}"
    parser_cls = get_parser(filename)
    parsed = parser_cls().parse_content(content) if parser_cls and content else None
    return ScannedFile(
        relative_path=f"locale/{lang}/{filename}",
        absolute_path=f"/tmp/locale/{lang}/{filename}",
        file_type=file_type,
        lang=lang,
        base_name=base_name,
        parsed=parsed,
    )


class TestContextCardBuilder:
    """Tests for build_context_card()."""

    def test_basic_intent_card(self) -> None:
        """Build context card for an intent file without analysis."""
        scanned = _make_scanned("hello", FileType.INTENT, "hello world\n")
        card = build_context_card(scanned)
        assert card.file_name == "hello"
        assert "Padatious" in card.file_type_label
        assert len(card.tips) > 0

    def test_intent_card_with_analysis(self) -> None:
        """Build context card linking intent to handler via analysis."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class TestSkill(OVOSSkill):
    @intent_handler("hello.intent")
    def handle_hello(self, message):
        self.speak_dialog("hello.world", {"name": "user"})
'''
        analyzer = SkillAnalyzer()
        analysis = analyzer.analyze_source(source)
        scanned = _make_scanned("hello", FileType.INTENT, "hello {name}\n")
        card = build_context_card(scanned, analysis)
        assert card.handler_method == "handle_hello"
        assert card.intent_system == "PADATIOUS"
        assert "hello.world" in card.triggers_dialog

    def test_vocab_card_with_adapt(self) -> None:
        """Build context card for a vocab file used by Adapt."""
        source = '''
from adapt.intent import IntentBuilder
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class TestSkill(OVOSSkill):
    @intent_handler(IntentBuilder("WeatherIntent").require("WeatherKeyword").optionally("Location"))
    def handle_weather(self, message):
        pass
'''
        analyzer = SkillAnalyzer()
        analysis = analyzer.analyze_source(source)
        scanned = _make_scanned("WeatherKeyword", FileType.VOCAB, "weather\nforecast\n")
        card = build_context_card(scanned, analysis)
        assert card.intent_system == "ADAPT"
        assert "WeatherIntent" in card.used_by_intents
        assert card.builder_chain is not None
        assert "WeatherKeyword" in card.builder_chain["require"]

    def test_dialog_card(self) -> None:
        """Build context card for a dialog file."""
        source = '''
from ovos_workshop.skills.ovos import OVOSSkill

class TestSkill(OVOSSkill):
    def handle_time(self, message):
        self.speak_dialog("time.current", {"time": "3:30"})
'''
        analyzer = SkillAnalyzer()
        analysis = analyzer.analyze_source(source)
        scanned = _make_scanned("time.current", FileType.DIALOG, "It is {time}\n")
        card = build_context_card(scanned, analysis)
        assert card.handler_method == "handle_time"
        assert "time" in card.slot_descriptions

    def test_tips_per_file_type(self) -> None:
        """Each file type should get appropriate tips."""
        for ft in [FileType.INTENT, FileType.VOCAB, FileType.DIALOG, FileType.ENTITY, FileType.REGEX, FileType.VALUE]:
            scanned = _make_scanned("test", ft)
            card = build_context_card(scanned)
            assert len(card.tips) > 0, f"No tips for {ft}"
