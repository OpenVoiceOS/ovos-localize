"""The page and the submission guard answer with one rule.

Both halves read ``data/locale_rules.json``. The table is built by
``ovos_localize.locale_rules`` and written by
``scripts/gen_locale_rules.py``, so a drift between the two halves can only
come from a stale table or from the page running a rule of its own. The
first is caught by ``TestTableIsCurrent`` and the second by
``TestPageAgreesWithGuard``, which runs the page's own function under node
over every tag in the table and compares the path AND the refusal reason
with the Python twin.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import langcodes

from ovos_localize.locale_rules import (
    BAD_SPELLING,
    OK,
    REGION_COLLISION,
    UNKNOWN_TAG,
    build_locale_rules,
    check_path_lang,
    compose_locale_path,
    load_locale_rules,
)

ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = ROOT / "index.html"
RULES_FILE = ROOT / "data" / "locale_rules.json"
RULES = load_locale_rules(str(RULES_FILE))

# The reference paths the review of d92ccfc ran, every tree shape the fleet
# ships: canonical regional, legacy lower-case regional, and region-less for
# a language with one region (fr, kab) and with several (es, pt, sw).
REFERENCES = (
    "locale/en-US/x.voc",
    "locale/en-us/x.voc",
    "locale/es/x.voc",
    "locale/fr/x.voc",
    "locale/kab/x.voc",
    "locale/pt/x.voc",
    "locale/sw/x.voc",
)

# Tags that carry a script or a variant subtag. None is in the enabled list
# today, which is why the page's own casing rule went unnoticed.
VARIANT_TAGS = ("ca-ES-valencia", "sr-Latn-RS", "zh-Hant-TW")


def _page_source() -> str:
    """The page's placement function, read out of index.html."""
    source = INDEX_HTML.read_text(encoding="utf-8")
    start = source.index("    function localePathForLangDetailed(")
    end = source.index("\n    }\n", start) + len("\n    }\n")
    return source[start:end]


def _page_source_named(*names) -> str:
    """Named functions of the page, read out of index.html."""
    source = INDEX_HTML.read_text(encoding="utf-8")
    blocks = []
    for name in names:
        start = source.index(f"    function {name}(")
        end = source.index("\n    }\n", start) + len("\n    }\n")
        blocks.append(source[start:end])
    return "\n".join(blocks)


def _page_place(cases: list) -> list:
    """Run the page's function over many cases in one node process.

    Args:
        cases: ``[[ref_path, tag], ...]``.

    Returns:
        One ``{path, reason, collidesWith}`` per case.
    """
    script = (
        _page_source()
        + "\nconst input = JSON.parse(process.argv[1]);\n"
        + "const rules = JSON.parse(process.argv[2]);\n"
        + "process.stdout.write(JSON.stringify(input.map("
        + "([ref, tag]) => localePathForLangDetailed(ref, tag, undefined, rules))));\n"
    )
    out = subprocess.run(
        ["node", "-e", script, json.dumps(cases), json.dumps(RULES)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


class TestTableIsCurrent(unittest.TestCase):
    def test_the_committed_table_is_what_the_module_builds(self):
        """A stale table is a page that runs yesterday's rule."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gen_locale_rules.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_the_table_carries_the_tags_both_halves_need(self):
        tags = RULES["tags"]
        coverage = json.loads((ROOT / "data" / "coverage.json").read_text(encoding="utf-8"))
        for tag in coverage["languages"]:
            self.assertIn(tag.lower(), tags, f"{tag} is enabled but not in the table")
        for tag in VARIANT_TAGS + ("kab-DZ",):
            self.assertIn(tag.lower(), tags)


class TestRuleContent(unittest.TestCase):
    def test_kab_dz_may_take_the_bare_kabyle_directory(self):
        # No other Kabyle region is written, and kab already means kab-DZ.
        self.assertTrue(RULES["tags"]["kab-dz"]["bare_ok"])
        self.assertEqual([], RULES["tags"]["kab-dz"]["rivals"])

    def test_a_language_with_two_regions_may_not(self):
        self.assertFalse(RULES["tags"]["pt-br"]["bare_ok"])
        self.assertEqual(["pt-AO", "pt-PT"], RULES["tags"]["pt-br"]["rivals"])

    def test_a_bare_tag_that_does_not_mean_the_region_may_not(self):
        # sw is not Kenya, so locale/sw is not sw-KE's home.
        self.assertFalse(RULES["tags"]["sw-ke"]["bare_ok"])

    def test_a_script_or_variant_subtag_keeps_its_own_case(self):
        self.assertEqual("ca-ES-valencia", RULES["tags"]["ca-es-valencia"]["canonical"])
        self.assertEqual("sr-Latn-RS", RULES["tags"]["sr-latn-rs"]["canonical"])
        self.assertEqual("zh-Hant-TW", RULES["tags"]["zh-hant-tw"]["canonical"])

    def test_every_spelling_of_a_tag_points_at_one_entry(self):
        self.assertEqual(RULES["tags"]["en-us"]["canonical"],
                         RULES["tags"]["en-US".lower()]["canonical"])
        self.assertEqual("kab-DZ", RULES["tags"]["kab-dz"]["canonical"])


class TestGuard(unittest.TestCase):
    def test_the_issue_564_payload_is_refused(self):
        reason, message = check_path_lang(
            "ovos_date_parser/locale/fr/months.voc", "kab", RULES)
        self.assertNotEqual(OK, reason)
        self.assertIn("kab", message)

    def test_kab_dz_into_the_bare_kabyle_directory_passes(self):
        self.assertEqual(OK, check_path_lang("locale/kab/x.voc", "kab-DZ", RULES)[0])
        self.assertEqual(OK, check_path_lang("locale/kab-dz/x.voc", "kab-DZ", RULES)[0])

    def test_the_portuguese_collision_is_refused_and_names_the_rivals(self):
        reason, message = check_path_lang("locale/pt/x.voc", "pt-BR", RULES)
        self.assertEqual(REGION_COLLISION, reason)
        self.assertIn("pt-PT", message)

    def test_an_upper_cased_script_directory_is_refused(self):
        reason, message = check_path_lang("locale/zh-HANT/x.voc", "zh-Hant", RULES)
        self.assertEqual(BAD_SPELLING, reason)
        self.assertIn("write 'zh-Hant'", message)
        self.assertEqual(OK, check_path_lang("locale/zh-Hant/x.voc", "zh-Hant", RULES)[0])

    def test_a_variant_directory_passes_in_its_own_case(self):
        self.assertEqual(
            OK, check_path_lang("locale/ca-ES-valencia/x.voc", "ca-ES-valencia", RULES)[0])

    def test_a_tag_the_platform_does_not_write_is_refused_as_such(self):
        reason, _ = check_path_lang("locale/xx/x.voc", "xx-YY", RULES)
        self.assertEqual(UNKNOWN_TAG, reason)


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's own function")
class TestPageAgreesWithGuard(unittest.TestCase):
    """The page and the guard, over every tag and every tree shape."""

    @classmethod
    def setUpClass(cls):
        cls.tags = sorted({entry["canonical"] for entry in RULES["tags"].values()})
        cls.cases = [[ref, tag] for ref in REFERENCES for tag in cls.tags]
        cls.page = _page_place(cls.cases)

    def test_the_page_and_the_python_twin_place_the_same_file(self):
        for (ref, tag), placed in zip(self.cases, self.page):
            twin = compose_locale_path(ref, tag, RULES)
            self.assertEqual(twin["path"], placed["path"], f"{ref} + {tag}")
            self.assertEqual(twin["reason"], placed["reason"], f"{ref} + {tag}")
            self.assertEqual(twin["rivals"] if placed["reason"] == REGION_COLLISION else
                             placed["collidesWith"], placed["collidesWith"], f"{ref} + {tag}")

    def test_the_guard_accepts_every_path_the_page_places(self):
        for (ref, tag), placed in zip(self.cases, self.page):
            if not placed["path"]:
                continue
            reason, message = check_path_lang(placed["path"], tag, RULES)
            self.assertEqual(OK, reason, f"{ref} + {tag} composed {placed['path']}: {message}")

    def test_the_page_stops_the_translator_wherever_the_guard_refuses(self):
        """The refusal branch of the workflow writes no comment by design, so
        a path the page places and the guard refuses is an issue that dies in
        silence. There must be none."""
        silent = []
        for (ref, tag), placed in zip(self.cases, self.page):
            if placed["path"] and check_path_lang(placed["path"], tag, RULES)[0] != OK:
                silent.append(f"{ref} + {tag} -> {placed['path']}")
        self.assertEqual([], silent)

    def test_the_variant_and_script_tags_agree_too(self):
        cases = [[ref, tag] for ref in REFERENCES for tag in VARIANT_TAGS]
        for (ref, tag), placed in zip(cases, _page_place(cases)):
            twin = compose_locale_path(ref, tag, RULES)
            self.assertEqual(twin["path"], placed["path"], f"{ref} + {tag}")
            self.assertEqual(twin["reason"], placed["reason"], f"{ref} + {tag}")
            if placed["path"]:
                self.assertEqual(
                    OK, check_path_lang(placed["path"], tag, RULES)[0],
                    f"{ref} + {tag} composed {placed['path']} and the guard refuses it")

    def test_kab_dz_passes_on_both_halves(self):
        placed = _page_place([["locale/kab/x.voc", "kab-DZ"]])[0]
        self.assertEqual("locale/kab/x.voc", placed["path"])
        self.assertEqual(OK, placed["reason"])
        self.assertEqual(OK, check_path_lang(placed["path"], "kab-DZ", RULES)[0])

    def test_no_reference_places_two_languages_on_one_file(self):
        """The property the whole change exists to establish.

        A file may be shared only by two spellings of one language, such as
        ``fr`` and ``fr-FR`` into ``locale/fr``. Two languages, such as
        ``pt-BR`` and ``pt-PT``, never share one."""
        for ref in REFERENCES:
            placed = {}
            for tag in self.tags:
                path = compose_locale_path(ref, tag, RULES)["path"]
                if path:
                    placed.setdefault(path, []).append(tag)
            for path, tags in placed.items():
                for one in tags:
                    for other in tags:
                        if one == other:
                            continue
                        self.assertEqual(
                            0, langcodes.tag_distance(one, other),
                            f"{ref}: {one} and {other} are different languages "
                            f"and both are written to {path}",
                        )


class TestBuildIsDeterministic(unittest.TestCase):
    def test_spelling_of_the_input_does_not_change_the_answer(self):
        one = build_locale_rules(["pt-BR", "pt-PT", "pt-AO"])
        other = build_locale_rules(["PT-br", "pt-pt", "pt-ao"])
        self.assertEqual(
            {k: v["canonical"] for k, v in one["tags"].items()},
            {k: v["canonical"] for k, v in other["tags"].items()},
        )


if __name__ == "__main__":
    unittest.main()


class TestRegionLessTagIntoANamedDirectory(unittest.TestCase):
    """The mirror of the collision this change exists to stop.

    A submission that says ``lang: pt`` with a path into ``locale/pt-PT``
    writes generic Portuguese over the European Portuguese file. The page
    never composes such a path, but a TRANSLATION_META block is written by
    whoever opens the issue, so the guard is the only barrier.
    """

    REFUSED = (
        ("locale/pt-BR/x.voc", "pt"),
        ("locale/pt-PT/x.voc", "pt"),
        ("locale/es-ES/x.voc", "es"),
        ("locale/es-419/x.voc", "es"),
        ("locale/nl-BE/x.voc", "nl"),
        ("locale/sv-SE/x.voc", "sv"),
        ("locale/ar-SA/x.voc", "ar"),
        ("locale/sr-Latn/x.voc", "sr"),
        ("locale/ca-ES-valencia/x.voc", "ca"),
    )

    def test_every_pair_the_review_named_is_refused(self):
        for file_path, lang in self.REFUSED:
            reason, message = check_path_lang(file_path, lang, RULES)
            self.assertEqual(REGION_COLLISION, reason, f"{lang} into {file_path}")
            self.assertIn("names no region", message)

    def test_the_only_region_of_a_language_still_passes(self):
        """fr-FR is what fr means and no other French region is written, so
        the two are one language written at two precisions, not two."""
        self.assertEqual(OK, check_path_lang("locale/fr-FR/x.voc", "fr", RULES)[0])
        self.assertEqual(OK, check_path_lang("locale/kab-DZ/x.voc", "kab", RULES)[0])

    def test_both_directions_agree(self):
        """Whatever passes one way passes the other, because the rule is
        the same table field read from either side."""
        for directory, tag in (("fr-FR", "fr"), ("kab-DZ", "kab")):
            self.assertEqual(OK, check_path_lang(f"locale/{directory}/x.voc", tag, RULES)[0])
            self.assertEqual(OK, check_path_lang(f"locale/{tag}/x.voc", directory, RULES)[0])
        for directory, tag in (("pt-PT", "pt"), ("sw-KE", "sw")):
            self.assertNotEqual(OK, check_path_lang(f"locale/{directory}/x.voc", tag, RULES)[0])
            self.assertNotEqual(OK, check_path_lang(f"locale/{tag}/x.voc", directory, RULES)[0])


@unittest.skipUnless(shutil.which("node"), "node is needed to run the page's own function")
class TestTableThatDidNotLoad(unittest.TestCase):
    """A fetch failure is a platform fault, never a missing language."""

    @staticmethod
    def _run(js: str, *args) -> str:
        script = (_page_source_named("localePathForLangDetailed", "pathRefusalMessage")
                  + "\n" + js)
        out = subprocess.run(["node", "-e", script, *args],
                             capture_output=True, text=True, check=True)
        return out.stdout

    def test_no_table_is_not_an_unknown_tag(self):
        js = ("const a = JSON.parse(process.argv[1]);\n"
              "process.stdout.write(JSON.stringify(a.map("
              "(rules) => localePathForLangDetailed('locale/en-US/x.voc', 'pt-PT', undefined, rules))));")
        # null (the fetch failed), an empty object, and an empty table.
        got = json.loads(self._run(js, json.dumps([None, {}, {"tags": {}}])))
        for placed in got:
            self.assertEqual("", placed["path"])
            self.assertEqual("table-not-loaded", placed["reason"])

    def test_the_call_site_says_which_fault_it_was(self):
        js = ("const reasons = JSON.parse(process.argv[1]);\n"
              "process.stdout.write(JSON.stringify(reasons.map("
              "(r) => pathRefusalMessage(r, 'pt-PT', ['pt-AO']))));")
        messages = json.loads(self._run(
            js, json.dumps(["table-not-loaded", "unknown-tag", "region-collision", "no-locale-root"])))
        table, unknown, collision, no_root = messages
        self.assertIn("did not load", table)
        self.assertIn("our side", table)
        # The translator must not read a platform fault as their language
        # being unsupported, or as a repository without a locale tree.
        self.assertNotIn("not a language", table)
        self.assertNotEqual(table, unknown)
        self.assertNotEqual(table, collision)
        self.assertNotEqual(table, no_root)
        self.assertIn("pt-AO", collision)

    def test_a_loaded_table_still_places_the_file(self):
        """The control: the same call with the real table places a path, so
        the case above cannot pass because the function always refuses."""
        js = ("const rules = JSON.parse(process.argv[1]);\n"
              "process.stdout.write(JSON.stringify("
              "localePathForLangDetailed('locale/en-US/x.voc', 'pt-PT', undefined, rules)));")
        placed = json.loads(self._run(js, json.dumps(RULES)))
        self.assertEqual("locale/pt-PT/x.voc", placed["path"])
        self.assertEqual(OK, placed["reason"])
