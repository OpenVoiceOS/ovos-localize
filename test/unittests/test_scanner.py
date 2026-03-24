"""Unit tests for the repo scanner / locale directory scanner."""

import os
import tempfile
from pathlib import Path

import pytest

from ovos_localize.enums import FileType
from ovos_localize.sync.github import scan_locale_directory, RepoScanner


class TestScanLocaleDirectory:
    """Tests for scan_locale_directory()."""

    def test_scan_simple_locale(self, tmp_path: Path) -> None:
        """Scan a simple locale directory with various file types."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        en.mkdir(parents=True)

        (en / "hello.intent").write_text("hello world\nhi there\n")
        (en / "weather.voc").write_text("weather\nforecast\n")
        (en / "greeting.dialog").write_text("Hello {name}\nHi {name}\n")

        files, bad = scan_locale_directory(str(locale))
        assert len(files) == 3
        assert bad == []

        types = {f.file_type for f in files}
        assert FileType.INTENT in types
        assert FileType.VOCAB in types
        assert FileType.DIALOG in types

    def test_multi_language(self, tmp_path: Path) -> None:
        """Scan locale directory with multiple languages."""
        locale = tmp_path / "locale"
        for lang in ["en-us", "de-de", "fr-fr"]:
            d = locale / lang
            d.mkdir(parents=True)
            (d / "hello.intent").write_text("hello\n")

        files, bad = scan_locale_directory(str(locale))
        langs = {f.lang for f in files}
        assert langs == {"en-US", "de-DE", "fr-FR"}
        assert bad == []

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Return empty list for nonexistent directory."""
        files, bad = scan_locale_directory(str(tmp_path / "nonexistent"))
        assert files == []
        assert bad == []

    def test_parsed_content(self, tmp_path: Path) -> None:
        """Verify files are parsed during scan."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        en.mkdir(parents=True)
        (en / "hello.intent").write_text("hello world\nhi there\n")

        files, bad = scan_locale_directory(str(locale))
        assert len(files) == 1
        assert bad == []
        assert files[0].parsed is not None
        assert files[0].parsed.line_count == 2

    def test_all_file_types(self, tmp_path: Path) -> None:
        """Detect all supported file types."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        en.mkdir(parents=True)

        (en / "test.intent").write_text("test\n")
        (en / "test.voc").write_text("test\n")
        (en / "test.dialog").write_text("test\n")
        (en / "test.entity").write_text("red\n")
        (en / "test.rx").write_text(r"(?P<Test>.*)" + "\n")
        (en / "test.value").write_text("display,system\n")
        (en / "skill.json").write_text('{"name": "Test"}')

        files, bad = scan_locale_directory(str(locale))
        assert bad == []
        types = {f.file_type for f in files}
        assert FileType.INTENT in types
        assert FileType.VOCAB in types
        assert FileType.DIALOG in types
        assert FileType.ENTITY in types
        assert FileType.REGEX in types
        assert FileType.VALUE in types
        assert FileType.SKILL_JSON in types


    def test_bad_lang_codes_flagged(self, tmp_path: Path) -> None:
        """Bare lang codes without region subtag are reported in bad_lang_codes."""
        locale = tmp_path / "locale"
        (locale / "en").mkdir(parents=True)
        (locale / "en" / "hello.intent").write_text("hello\n")
        (locale / "en-US").mkdir(parents=True)
        (locale / "en-US" / "hello.intent").write_text("hello\n")

        files, bad = scan_locale_directory(str(locale))
        assert "en" in bad
        assert "en-US" not in bad
        # Both files should still be present and normalised to en-US
        assert all(f.lang == "en-US" for f in files)


class TestRepoScanner:
    """Tests for RepoScanner."""

    def test_find_skill_source(self, tmp_path: Path) -> None:
        """Find the main skill Python file."""
        pkg = tmp_path / "my_skill"
        pkg.mkdir()
        init = pkg / "__init__.py"
        init.write_text('''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler("hello.intent")
    def handle_hello(self, message):
        self.speak_dialog("hello")
''')
        result = RepoScanner._find_skill_source(tmp_path)
        assert result == init

    def test_find_locale_dir(self, tmp_path: Path) -> None:
        """Find the locale directory."""
        locale = tmp_path / "locale"
        en = locale / "en-us"
        en.mkdir(parents=True)
        (en / "hello.intent").write_text("hello\n")

        result = RepoScanner._find_locale_dir(tmp_path)
        assert result == locale

    def test_scan_integration(self, tmp_path: Path) -> None:
        """Full scan of a mock skill repo."""
        # Create skill source
        pkg = tmp_path / "my_skill"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class MySkill(OVOSSkill):
    @intent_handler("hello.intent")
    def handle_hello(self, message):
        self.speak_dialog("greeting", {"name": "world"})
''')

        # Create locale files
        locale = tmp_path / "locale" / "en-us"
        locale.mkdir(parents=True)
        (locale / "hello.intent").write_text("hello\nhi\nhey there\n")
        (locale / "greeting.dialog").write_text("Hello {name}\nHi {name}\n")

        scanner = RepoScanner(str(tmp_path / "repos"))
        result = scanner.scan(str(tmp_path))

        assert result.skill_class_name == "MySkill"
        assert len(result.locale_files) == 2
        assert "en-US" in result.languages
        assert result.skill_analysis is not None
        assert "hello.intent" in result.skill_analysis.intent_file_to_handler
