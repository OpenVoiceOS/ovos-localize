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
    canonical_lang_spelling,
    check_path_lang,
    load_supported_langs,
    locale_dir_from_path,
    locale_dir_matches_lang,
    regional_siblings,
)

# file_path and lang as the page wrote them into the issue bodies.
ISSUE_564 = ("ovos_date_parser/locale/fr/months.voc", "kab")
ISSUE_491 = ("ovos_date_parser/locale/fr/era_year_ref.voc", "kab")
# A skill submission with an en-US reference, the path the page writes today.
SKILL_OK = ("locale/pt-PT/what.time.is.it.intent", "pt-PT")

INDEX_HTML = Path(__file__).resolve().parents[2] / "index.html"
COVERAGE = Path(__file__).resolve().parents[2] / "data" / "coverage.json"
SUPPORTED = load_supported_langs(str(COVERAGE))

# Locale directories written in lower case. Every one is the canonical tag
# lower-cased, and they are already shipped, so the guard accepts that
# spelling and no other: ca-es, da-dk, de-de, en-us, es-es, eu-es, fa-ir,
# fr-fr, gl-es, it-it, kab-dz, nb-no, nl-be, nl-nl, pl-pl, pt-br, pt-pt,
# sv-se and uk-ua, read out of the 200 manifests in data/skills.
LEGACY_LOWER_CASE_DIRS = ("en-us", "kab-dz", "pt-br", "fa-ir")


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
        # Kabyle reaches the page as kab from one repo and kab-DZ from
        # another, and no other Kabyle region is supported.
        self.assertTrue(locale_dir_matches_lang("kab", "kab-DZ", SUPPORTED))
        self.assertTrue(locale_dir_matches_lang("kab-DZ", "kab", SUPPORTED))
        self.assertTrue(locale_dir_matches_lang("fr", "fr-FR", SUPPORTED))

    def test_a_bare_directory_of_a_multi_region_language_is_refused(self):
        # locale/pt names neither pt-BR nor pt-PT, and both are supported.
        self.assertFalse(locale_dir_matches_lang("pt", "pt-BR", SUPPORTED))
        self.assertFalse(locale_dir_matches_lang("pt", "pt-PT", SUPPORTED))
        # sw-KE is not what the bare sw tag means, so locale/sw is not its home.
        self.assertFalse(locale_dir_matches_lang("sw", "sw-KE", SUPPORTED))

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
        self.assertIsNone(check_path_lang(*SKILL_OK, SUPPORTED))

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
    def _page_source() -> str:
        """The page's own composition functions, read out of index.html."""
        source = INDEX_HTML.read_text(encoding="utf-8")
        blocks = []
        for name in ("canonicalLangSpelling", "sameLanguageTags",
                     "localePathForLangDetailed", "localePathForLang"):
            start = source.index(f"    function {name}(")
            end = source.index("\n    }\n", start) + len("\n    }\n")
            blocks.append(source[start:end])
        return "\n".join(blocks)

    @classmethod
    def compose(cls, ref_path: str, target_lang: str, file_key: str | None = None,
                supported: list | None = None) -> str:
        script = (
            cls._page_source()
            + "\nconst a = JSON.parse(process.argv[1]);\n"
            + "process.stdout.write(localePathForLang(a[0], a[1], a[2] || undefined, a[3]));\n"
        )
        out = subprocess.run(
            ["node", "-e", script,
             json.dumps([ref_path, target_lang, file_key,
                         SUPPORTED if supported is None else supported])],
            capture_output=True, text=True, check=True,
        )
        return out.stdout

    def test_a_french_reference_gives_a_kabyle_path(self):
        # The exact reference the #564 translator read.
        composed = self.compose("ovos_date_parser/locale/fr/months.voc", "kab")
        self.assertEqual(composed, "ovos_date_parser/locale/kab/months.voc")
        self.assertIsNone(check_path_lang(composed, "kab", SUPPORTED))

    def test_the_refused_payloads_cannot_be_composed(self):
        for ref_path, lang in (ISSUE_564, ISSUE_491):
            composed = self.compose(ref_path, lang)
            self.assertNotEqual(composed, ref_path)
            self.assertIsNone(check_path_lang(composed, lang, SUPPORTED))

    def test_an_en_us_reference_still_passes(self):
        composed = self.compose("locale/en-US/what.time.is.it.intent", "pt-PT")
        self.assertEqual(composed, "locale/pt-PT/what.time.is.it.intent")
        self.assertIsNone(check_path_lang(composed, "pt-PT", SUPPORTED))

    def test_a_path_with_no_locale_root_is_not_placed(self):
        self.assertEqual(self.compose("README.md", "kab"), "")


if __name__ == "__main__":
    sys.exit(unittest.main())


class TestRegionalSiblings(unittest.TestCase):
    def test_portuguese_has_siblings(self):
        self.assertEqual(["pt-AO", "pt-PT"], regional_siblings("pt-BR", SUPPORTED))

    def test_kabyle_and_french_have_none(self):
        # The only supported Kabyle tag is the region-less kab, which is the
        # same language written less precisely, not another region.
        self.assertEqual([], regional_siblings("kab-DZ", SUPPORTED))
        self.assertEqual([], regional_siblings("fr-FR", SUPPORTED))


class TestRegionlessDirectory(unittest.TestCase):
    """A region-less directory names no single region.

    ovos-date-parser ships locale/{de,es,fr,it,pt}. Before this rule a pt-BR
    submission and a pt-PT submission were both written to locale/pt, so the
    second overwrote the first: the ovos-date-parser#333-#336 accident, one
    subtag narrower.
    """

    def test_pt_br_and_pt_pt_are_both_refused_in_a_bare_pt_tree(self):
        for lang in ("pt-BR", "pt-PT"):
            problem = check_path_lang("ovos_date_parser/locale/pt/months.voc", lang, SUPPORTED)
            self.assertIsNotNone(problem, f"{lang} must not be written to locale/pt")
            self.assertIn("region", problem)

    def test_the_named_sibling_is_in_the_message(self):
        problem = check_path_lang("locale/pt/x.voc", "pt-BR", SUPPORTED)
        self.assertIn("pt-PT", problem)

    def test_a_language_with_one_supported_region_still_passes(self):
        self.assertIsNone(check_path_lang("ovos_date_parser/locale/fr/months.voc", "fr-FR", SUPPORTED))

    def test_kab_dz_against_its_own_bare_directory_passes(self):
        self.assertIsNone(check_path_lang("locale/kab/x.voc", "kab-DZ", SUPPORTED))
        self.assertIsNone(check_path_lang("locale/kab-dz/x.voc", "kab-DZ", SUPPORTED))

    def test_without_the_supported_list_a_regional_tag_is_refused(self):
        # The question cannot be answered, so the guard does not guess.
        self.assertIsNotNone(check_path_lang("locale/pt/x.voc", "pt-BR"))
        self.assertIsNone(check_path_lang("locale/pt-BR/x.voc", "pt-BR"))


class TestDirectorySpelling(unittest.TestCase):
    def test_script_subtag_is_title_case(self):
        self.assertEqual("zh-Hant", canonical_lang_spelling("zh-HANT"))
        self.assertEqual("sr-Latn", canonical_lang_spelling("sr-LATN"))
        self.assertEqual("kab-DZ", canonical_lang_spelling("kab-dz"))

    def test_an_upper_cased_script_directory_is_refused(self):
        problem = check_path_lang("locale/zh-HANT/x.voc", "zh-Hant", SUPPORTED)
        self.assertIsNotNone(problem)
        self.assertIn("zh-Hant", problem)
        self.assertIsNone(check_path_lang("locale/zh-Hant/x.voc", "zh-Hant", SUPPORTED))

    def test_the_lower_case_legacy_directories_still_pass(self):
        for directory in LEGACY_LOWER_CASE_DIRS:
            lang = canonical_lang_spelling(directory)
            self.assertIsNone(
                check_path_lang(f"locale/{directory}/x.voc", lang, SUPPORTED),
                f"locale/{directory} is a shipped directory and must pass",
            )


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's own function")
class TestComposedPathIsInjective(TestPagePathComposition):
    """One reference path never gives one file path for two supported tags.

    This is the property the region-dropping defect broke: in a region-less
    tree every region of a language composed the same path.
    """

    def _composed_paths(self, ref_path: str) -> dict:
        placed = {}
        for tag in SUPPORTED:
            path = self.compose(ref_path, tag)
            if path:
                placed.setdefault(path, []).append(tag)
        return placed

    def test_a_region_less_reference_is_injective(self):
        for ref_path in ("locale/es/x.voc", "locale/fr/x.voc"):
            shared = {p: t for p, t in self._composed_paths(ref_path).items() if len(t) > 1}
            self.assertEqual({}, shared, f"{ref_path} places two tags on one file: {shared}")

    def test_a_regional_reference_is_injective(self):
        shared = {p: t for p, t in self._composed_paths("locale/en-US/x.voc").items() if len(t) > 1}
        self.assertEqual({}, shared, f"locale/en-US places two tags on one file: {shared}")

    def test_pt_br_and_pt_pt_are_the_named_case(self):
        # Region-less reference: neither is placed, and the page says so.
        self.assertEqual("", self.compose("locale/es/x.voc", "pt-BR"))
        self.assertEqual("", self.compose("locale/es/x.voc", "pt-PT"))
        # Regional reference: both are placed, each in its own directory.
        self.assertEqual("locale/pt-BR/x.voc", self.compose("locale/en-US/x.voc", "pt-BR"))
        self.assertEqual("locale/pt-PT/x.voc", self.compose("locale/en-US/x.voc", "pt-PT"))

    def test_every_composed_path_passes_the_guard(self):
        for ref_path in ("locale/es/x.voc", "locale/fr/x.voc", "locale/en-US/x.voc"):
            for tag in SUPPORTED:
                path = self.compose(ref_path, tag)
                if path:
                    self.assertIsNone(
                        check_path_lang(path, tag, SUPPORTED),
                        f"the page composed {path} for {tag} and the guard refuses it",
                    )

    def test_the_script_subtag_is_not_upper_cased(self):
        self.assertEqual("locale/zh-Hant/x.voc",
                         self.compose("locale/en-US/x.voc", "zh-Hant", supported=["zh-Hant"]))
