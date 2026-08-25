"""Unit tests for the data generation script."""

import json
import sys
from pathlib import Path
from typing import Dict, List

import pytest

# Add scripts/ to path so we can import generate_data
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from generate_data import (
    build_coverage_json,
    build_issues_json,
    build_repos_json,
    build_skill_json,
    build_validation_json,
    load_skills_list,
)

from ovos_localize.sync.github import RepoScanner


class TestLoadSkillsList:
    """Tests for load_skills_list()."""

    def test_load_valid_file(self, tmp_path: Path) -> None:
        """Parse org/repo lines from skills.txt."""
        f = tmp_path / "skills.txt"
        f.write_text("OpenVoiceOS/ovos-skill-hello-world\nOpenVoiceOS/ovos-skill-weather\n")
        result = load_skills_list(f)
        assert result == [
            ("OpenVoiceOS", "ovos-skill-hello-world"),
            ("OpenVoiceOS", "ovos-skill-weather"),
        ]

    def test_skip_comments_and_blanks(self, tmp_path: Path) -> None:
        """Skip comment lines and blank lines."""
        f = tmp_path / "skills.txt"
        f.write_text("# comment\n\nOpenVoiceOS/ovos-skill-test\n  \n")
        result = load_skills_list(f)
        assert len(result) == 1
        assert result[0] == ("OpenVoiceOS", "ovos-skill-test")

    def test_missing_file(self, tmp_path: Path) -> None:
        """Return empty list for missing file."""
        result = load_skills_list(tmp_path / "nonexistent.txt")
        assert result == []


class TestBuildSkillJson:
    """Tests for build_skill_json()."""

    def test_basic_skill(self, tmp_path: Path) -> None:
        """Build JSON for a simple skill repo."""
        # Create mock skill
        pkg = tmp_path / "my_skill"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('''
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler

class HelloSkill(OVOSSkill):
    @intent_handler("hello.intent")
    def handle_hello(self, message):
        self.speak_dialog("greeting", {"name": "world"})
''')
        locale = tmp_path / "locale"
        en = locale / "en-US"
        de = locale / "de-DE"
        en.mkdir(parents=True)
        de.mkdir(parents=True)
        (en / "hello.intent").write_text("hello\nhi\nhey there\n")
        (en / "greeting.dialog").write_text("Hello {name}\nHi {name}\n")
        (de / "hello.intent").write_text("hallo\nhi\n")

        scanner = RepoScanner(str(tmp_path / "repos"))
        scan = scanner.scan(str(tmp_path))
        result = build_skill_json(scan, "OpenVoiceOS", "ovos-skill-hello")

        assert result["id"] == "ovos-skill-hello"
        assert result["repo"] == "OpenVoiceOS/ovos-skill-hello"
        assert result["skill_class"] == "HelloSkill"
        assert "en-US" in result["languages"]
        assert "de-DE" in result["languages"]
        assert len(result["files"]) >= 2

    def test_edit_urls(self, tmp_path: Path) -> None:
        """Edit URLs are properly constructed."""
        locale = tmp_path / "locale" / "en-US"
        locale.mkdir(parents=True)
        (locale / "test.voc").write_text("test\n")

        scanner = RepoScanner(str(tmp_path / "repos"))
        scan = scanner.scan(str(tmp_path))
        result = build_skill_json(scan, "TestOrg", "test-skill")

        for file_data in result["files"].values():
            for lang, url in file_data["edit_urls"].items():
                assert "github.com/TestOrg/test-skill/edit/dev/" in url

    def test_validation_included(self, tmp_path: Path) -> None:
        """Validation issues appear in per-lang data."""
        locale = tmp_path / "locale"
        en = locale / "en-US"
        de = locale / "de-DE"
        en.mkdir(parents=True)
        de.mkdir(parents=True)
        # en-us has slot {name}, de-de is missing it
        (en / "greeting.dialog").write_text("Hello {name}\nHi {name}\n")
        (de / "greeting.dialog").write_text("Hallo\nHi\n")

        scanner = RepoScanner(str(tmp_path / "repos"))
        scan = scanner.scan(str(tmp_path))
        result = build_skill_json(scan, "Test", "test-skill")

        dialog_file = None
        for fk, fd in result["files"].items():
            if fd["type"] == "dialog":
                dialog_file = fd
                break

        assert dialog_file is not None
        de_data = dialog_file["langs"]["de-DE"]
        # Should have missing_variables error
        error_rules = [v["rule_name"] for v in de_data["validation"]]
        assert "dialog.missing_variables" in error_rules


class TestBuildCoverageJson:
    """Tests for build_coverage_json()."""

    def test_coverage_matrix(self) -> None:
        """Coverage matrix has correct structure."""
        skills = [
            {
                "id": "skill-a",
                "languages": ["en-US", "de-DE"],
                "files": {
                    "hello.intent": {
                        "type": "intent",
                        "langs": {
                            "en-US": {"validation": []},
                            "de-DE": {"validation": []},
                        }
                    },
                    "world.intent": {
                        "type": "intent",
                        "langs": {
                            "en-US": {"validation": []},
                        }
                    },
                }
            }
        ]
        result = build_coverage_json(skills)
        assert "skill-a" in result["skills"]
        assert "en-US" in result["languages"]
        assert "de-DE" in result["languages"]
        assert "skill-a" in result["matrix"]
        # de-de has 1/2 intent files = 50%
        assert result["matrix"]["skill-a"]["de-DE"]["combined_pct"] == 50.0


class TestBuildReposJson:
    """Tests for build_repos_json()."""

    def test_repos_index(self) -> None:
        """Repos index has correct fields."""
        skills = [
            {
                "id": "skill-a",
                "repo": "Org/skill-a",
                "skill_class": "SkillA",
                "languages": ["en-US"],
                "files": {
                    "f1": {"langs": {"en-US": {}}},
                }
            }
        ]
        result = build_repos_json(skills)
        assert len(result) == 1
        assert result[0]["id"] == "skill-a"
        assert result[0]["file_count"] == 1


class TestBuildValidationJson:
    """Tests for build_validation_json()."""

    def test_aggregation(self) -> None:
        """Validation stats are aggregated correctly."""
        skills = [
            {
                "id": "skill-a",
                "files": {
                    "f1": {
                        "langs": {
                            "en-US": {"validation": []},
                            "de-DE": {"validation": [
                                {"rule_name": "intent.min_lines", "severity": "warning", "message": "too few"},
                                {"rule_name": "intent.missing_slots", "severity": "error", "message": "missing"},
                            ]},
                        }
                    }
                }
            }
        ]
        result = build_validation_json(skills)
        assert result["total_errors"] == 1
        assert result["total_warnings"] == 1
        assert result["by_rule"]["intent.min_lines"] == 1
        assert result["by_rule"]["intent.missing_slots"] == 1
        assert result["by_skill"][0]["id"] == "skill-a"
        assert result["by_skill"][0]["errors"] == 1


class TestEnabledLanguagesReachProduction:
    """The wiring, not just the library function.

    Every other test calls ``merge_equivalent_langs`` directly, so deleting
    ``canonical_codes=enabled_langs`` from ``build_coverage_json`` left the
    whole suite green while the bug returned in production.
    """

    @staticmethod
    def _skill(langs):
        return {
            "id": "s", "repo": "o/s", "skill_class": "", "branch": "dev",
            "languages": list(langs), "bad_lang_codes": [], "locale_dir": "locale",
            "files": {},
        }

    def test_enabled_code_wins_through_build_coverage_json(self) -> None:
        """kab is enabled, so a stray kab-DZ must merge into it, not vice versa."""
        cov = build_coverage_json([self._skill(["kab", "kab-DZ", "en-US"])])
        assert cov["merge_map"]["kab-DZ"] == "kab"
        assert cov["merge_map"]["kab"] == "kab"
        assert "kab-DZ" not in cov["languages"]

    def test_unenabled_pair_still_prefers_the_specific_tag(self) -> None:
        cov = build_coverage_json([self._skill(["da", "da-DK"])])
        assert cov["merge_map"]["da"] == "da-DK"


class TestBareLangCodeIssues:
    """Codes the scanner reports as bad become actionable rename requests.

    Whether a region-less code counts as bad is decided by the scanner, in
    ``scan_locale_directory``; see ``test_scanner.py``."""

    @staticmethod
    def _skill(bad):
        return {
            "id": "s", "repo": "o/s", "skill_class": "", "branch": "dev",
            "languages": ["en-US"], "bad_lang_codes": list(bad),
            "locale_dir": "locale", "files": {},
        }

    def test_genuinely_bare_code_is_still_reported(self) -> None:
        """de -> de-DE is a real fix and must survive."""
        issues = build_issues_json([self._skill(["de"])])["issues"]
        bad = [i for i in issues if i["type"] == "bad_lang_code"]
        assert len(bad) == 1
        assert bad[0]["code"] == "de" and bad[0]["normalized"] == "de-DE"
class TestBranchPropagation:
    """The resolved branch must reach the SPA, which submits against it.

    Before this, every generated edit URL and every submission targeted
    ``dev``, so any skill repo on ``main`` or ``master`` silently lost the
    translation.
    """

    @staticmethod
    def _scan(tmp_path: Path):
        locale = tmp_path / "locale" / "en-US"
        locale.mkdir(parents=True)
        (locale / "test.voc").write_text("test\n")
        return RepoScanner(str(tmp_path / "repos")).scan(str(tmp_path))

    def test_skill_json_carries_resolved_branch(self, tmp_path: Path) -> None:
        scan = self._scan(tmp_path)
        scan.branch = "main"
        result = build_skill_json(scan, "TestOrg", "test-skill")
        assert result["branch"] == "main"

    def test_edit_urls_use_resolved_branch(self, tmp_path: Path) -> None:
        scan = self._scan(tmp_path)
        scan.branch = "master"
        result = build_skill_json(scan, "TestOrg", "test-skill")
        urls = [u for fd in result["files"].values() for u in fd["edit_urls"].values()]
        assert urls, "expected at least one edit URL"
        assert all("/edit/master/" in u for u in urls)

    def test_explicit_branch_overrides_scan(self, tmp_path: Path) -> None:
        scan = self._scan(tmp_path)
        scan.branch = "main"
        result = build_skill_json(scan, "TestOrg", "test-skill", branch="release")
        assert result["branch"] == "release"

    def test_repos_json_exposes_branch(self, tmp_path: Path) -> None:
        scan = self._scan(tmp_path)
        scan.branch = "main"
        skill = build_skill_json(scan, "TestOrg", "test-skill")
        assert build_repos_json([skill])[0]["branch"] == "main"
