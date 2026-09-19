"""Tests for the path-against-language check on translation submissions.

The real payloads of ovos-localize#564 (merged as ovos-date-parser#333-#336)
and of the still-open #491 are used, because the defect they carry is the
reason the check exists.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from ovos_localize.cli.check_path_lang import main as check_main
from ovos_localize.lang_utils import (
    check_path_lang,
    locale_dir_from_path,
    locale_dir_matches_lang,
)

# file_path and lang as the page wrote them into the issue bodies.
ISSUE_564 = ("ovos_date_parser/locale/fr/months.voc", "kab")
ISSUE_491 = ("ovos_date_parser/locale/fr/era_year_ref.voc", "kab")
# A skill submission with an en-US reference, the path the page writes today.
SKILL_OK = ("locale/pt-PT/what.time.is.it.intent", "pt-PT")

INDEX_HTML = Path(__file__).resolve().parents[2] / "index.html"


class TestLocaleDirFromPath(unittest.TestCase):
    def test_locale_root_inside_a_package(self):
        self.assertEqual(locale_dir_from_path("ovos_date_parser/locale/fr/months.voc"), "fr")

    def test_res_root(self):
        self.assertEqual(locale_dir_from_path("res/en-US/dialog/hi.dialog"), "en-US")

    def test_no_locale_root(self):
        self.assertIsNone(locale_dir_from_path("README.md"))

    def test_locale_root_with_no_file_after_the_language(self):
        self.assertIsNone(locale_dir_from_path("locale/fr"))


class TestLocaleDirMatchesLang(unittest.TestCase):
    def test_same_tag(self):
        self.assertTrue(locale_dir_matches_lang("kab", "kab"))

    def test_region_on_one_side_only(self):
        # Kabyle reaches the page as kab from one repo and kab-DZ from another.
        self.assertTrue(locale_dir_matches_lang("kab", "kab-DZ"))
        self.assertTrue(locale_dir_matches_lang("kab-DZ", "kab"))
        self.assertTrue(locale_dir_matches_lang("fr", "fr-FR"))

    def test_alias_tags(self):
        self.assertTrue(locale_dir_matches_lang("pt", "pt-BR"))

    def test_two_different_regions_are_two_languages(self):
        self.assertFalse(locale_dir_matches_lang("en-US", "en-GB"))
        self.assertFalse(locale_dir_matches_lang("pt-BR", "pt-PT"))

    def test_different_languages(self):
        self.assertFalse(locale_dir_matches_lang("fr", "kab"))

    def test_empty(self):
        self.assertFalse(locale_dir_matches_lang("", "kab"))
        self.assertFalse(locale_dir_matches_lang("fr", ""))


class TestCheckPathLang(unittest.TestCase):
    def test_issue_564_payload_is_refused(self):
        problem = check_path_lang(*ISSUE_564)
        self.assertIsNotNone(problem)
        self.assertIn("'fr'", problem)
        self.assertIn("kab", problem)

    def test_issue_491_payload_is_refused(self):
        self.assertIsNotNone(check_path_lang(*ISSUE_491))

    def test_skill_payload_passes(self):
        self.assertIsNone(check_path_lang(*SKILL_OK))

    def test_path_with_no_language_directory_is_refused(self):
        self.assertIsNotNone(check_path_lang("README.md", "kab"))


class TestCheckPathLangCli(unittest.TestCase):
    def test_cli_exit_codes(self):
        self.assertEqual(check_main([ISSUE_564[0], "--lang", ISSUE_564[1]]), 1)
        self.assertEqual(check_main([SKILL_OK[0], "--lang", SKILL_OK[1]]), 0)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's own function")
class TestPagePathComposition(unittest.TestCase):
    """The page must not be able to compose the refused payload at all."""

    @staticmethod
    def compose(ref_path: str, target_lang: str, file_key: str | None = None) -> str:
        source = INDEX_HTML.read_text(encoding="utf-8")
        start = source.index("    function localePathForLang(")
        end = source.index("\n    }\n", start) + len("\n    }\n")
        script = (
            source[start:end]
            + "\nconst a = JSON.parse(process.argv[1]);\n"
            + "process.stdout.write(localePathForLang(a[0], a[1], a[2] || undefined));\n"
        )
        out = subprocess.run(
            ["node", "-e", script, json.dumps([ref_path, target_lang, file_key])],
            capture_output=True, text=True, check=True,
        )
        return out.stdout

    def test_a_french_reference_gives_a_kabyle_path(self):
        # The exact reference the #564 translator read.
        composed = self.compose("ovos_date_parser/locale/fr/months.voc", "kab")
        self.assertEqual(composed, "ovos_date_parser/locale/kab/months.voc")
        self.assertIsNone(check_path_lang(composed, "kab"))

    def test_the_refused_payloads_cannot_be_composed(self):
        for ref_path, lang in (ISSUE_564, ISSUE_491):
            composed = self.compose(ref_path, lang)
            self.assertNotEqual(composed, ref_path)
            self.assertIsNone(check_path_lang(composed, lang))

    def test_an_en_us_reference_still_passes(self):
        composed = self.compose("locale/en-US/what.time.is.it.intent", "pt-PT")
        self.assertEqual(composed, "locale/pt-PT/what.time.is.it.intent")
        self.assertIsNone(check_path_lang(composed, "pt-PT"))

    def test_a_path_with_no_locale_root_is_not_placed(self):
        self.assertEqual(self.compose("README.md", "kab"), "")


if __name__ == "__main__":
    sys.exit(unittest.main())
