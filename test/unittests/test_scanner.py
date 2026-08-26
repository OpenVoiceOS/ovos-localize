"""Unit tests for the repo scanner / locale directory scanner."""

import os
from pathlib import Path

from ovos_localize.enums import FileType
from ovos_localize.sync.github import RepoScanner, scan_locale_directory


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

    def test_kabyle_bare_code_not_flagged_as_bad(self, tmp_path: Path) -> None:
        """kab has no commonly-used region subtag and normalizes to itself
        — it must not be reported in bad_lang_codes just for lacking a
        hyphen, and the scan must not throw on a region-less 3-letter
        locale directory name."""
        locale = tmp_path / "locale"
        (locale / "kab").mkdir(parents=True)
        (locale / "kab" / "hello.intent").write_text("azul\n")

        files, bad = scan_locale_directory(str(locale))
        assert "kab" not in bad
        assert len(files) == 1
        assert files[0].lang == "kab"


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


class TestResolvedBranch:
    """The branch a repo actually uses must survive into the scan result.

    Skill repos do not agree on a branch name: OVOS uses ``dev``, many
    community repos use ``main`` or ``master``.  Assuming ``dev`` makes
    translation submissions target a ref that does not exist, and the
    submission is lost with no feedback to the translator.
    """

    @staticmethod
    def _git_repo(path: Path, branch: str) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        os.system(f"git -C {path} init -q -b {branch}")
        os.system(f"git -C {path} config user.email t@t.t")
        os.system(f"git -C {path} config user.name t")
        (path / "README.md").write_text("x\n")
        os.system(f"git -C {path} add -A && git -C {path} commit -qm init")
        return path

    def test_current_branch_reports_main(self, tmp_path: Path) -> None:
        """A repo checked out on ``main`` reports ``main``, not ``dev``."""
        repo = self._git_repo(tmp_path / "r", "main")
        assert RepoScanner._current_branch(repo) == "main"

    def test_scan_result_defaults_to_empty_branch(self) -> None:
        """``branch`` is unset until a sync resolves it."""
        from ovos_localize.sync.github import ScanResult
        assert ScanResult(repo_path="/tmp/x").branch == ""

    def test_clone_or_pull_returns_resolved_branch(self, tmp_path: Path) -> None:
        """An existing checkout reports the branch it is really on."""
        scanner = RepoScanner(str(tmp_path / "repos"))
        self._git_repo(tmp_path / "repos" / "org" / "repo", "master")
        _, branch = scanner.clone_or_pull("org", "repo", "dev")
        assert branch == "master"

    def test_detached_head_reports_no_branch(self, tmp_path: Path) -> None:
        """A detached HEAD has no branch name.

        ``git rev-parse --abbrev-ref HEAD`` answers the literal ``"HEAD"``
        there.  Passing that through would put ``branch: HEAD`` into a
        translation submission and lose it exactly as a wrong branch does.
        """
        repo = self._git_repo(tmp_path / "d", "main")
        os.system(f"git -C {repo} checkout -q --detach")
        assert RepoScanner._current_branch(repo) == ""


class TestHumanFirstLanguageGate:
    """The SPA hides machine-translation suggestions for human-first languages.

    The gate is JavaScript, so this asserts the contract it relies on: the
    same language arrives as ``kab`` from one repo and ``kab-DZ`` from
    another, depending on how each locale directory was named, so matching
    the full tag would leave the suggestion button visible on most repos.
    """

    def test_gate_matches_on_primary_subtag(self) -> None:
        html = (Path(__file__).resolve().parents[2] / "index.html").read_text()
        assert "const isHumanFirst = (lang) =>" in html
        assert "split('-')[0].toLowerCase()" in html

    def test_gate_is_used_instead_of_exact_match(self) -> None:
        html = (Path(__file__).resolve().parents[2] / "index.html").read_text()
        assert "isHumanFirstLang = isHumanFirst(lang)" in html
        assert "HUMAN_FIRST_LANGS.has(lang)" not in html


class TestEditorAccessibilityContract:
    """Contracts the editor markup must keep.

    These live in index.html, which no other test executes, so the parts a
    keyboard or screen-reader user depends on are asserted here.
    """

    @staticmethod
    def _html() -> str:
        return (Path(__file__).resolve().parents[2] / "index.html").read_text()

    def test_skip_link_does_not_navigate(self) -> None:
        """The router owns location.hash.

        Following the skip link would route to an unknown view and throw away
        an unsaved translation, so it must cancel the navigation.
        """
        html = self._html()
        line = next(x for x in html.split("\n") if "skip-link" in x and "<a " in x)
        assert "event.preventDefault()" in line

    def test_skip_target_is_focusable_and_visible(self) -> None:
        html = self._html()
        assert 'id="app"' in html
        assert "#app:focus { outline: none; }" not in html

    def test_json_fields_are_labelled(self) -> None:
        """Every generated label points at the control it names."""
        html = self._html()
        start = html.index("const fieldId")
        block = html[start:start + 4500]
        assert block.count("""label for="' + fieldId""") == 3
        assert block.count("""id="' + fieldId""") == 3
