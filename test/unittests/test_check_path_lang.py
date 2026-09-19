"""The submission guard, on the payloads that made it necessary.

The rule itself, and the agreement between the page and the guard, are
measured in ``test_locale_rules.py``. What is measured here is the command
the workflow runs: the real issue payloads of ovos-localize#564 and #491,
and the exit codes the workflow branches on.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ovos_localize.cli.check_path_lang import SETUP_ERROR
from ovos_localize.cli.check_path_lang import main as check_main
from ovos_localize.locale_rules import OK, check_path_lang, load_locale_rules

ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = str(ROOT / "data" / "locale_rules.json")
RULES = load_locale_rules(RULES_FILE)

# file_path and lang as the page wrote them into the issue bodies.
ISSUE_564 = ("ovos_date_parser/locale/fr/months.voc", "kab")
ISSUE_491 = ("ovos_date_parser/locale/fr/era_year_ref.voc", "kab")
# A skill submission with an en-US reference, the path the page writes today.
SKILL_OK = ("locale/pt-PT/what.time.is.it.intent", "pt-PT")


class TestRealPayloads(unittest.TestCase):
    def test_issue_564_payload_is_refused(self):
        reason, message = check_path_lang(*ISSUE_564, RULES)
        self.assertNotEqual(OK, reason)
        self.assertIn("'fr'", message)
        self.assertIn("kab", message)

    def test_issue_491_payload_is_refused(self):
        self.assertNotEqual(OK, check_path_lang(*ISSUE_491, RULES)[0])

    def test_skill_payload_passes(self):
        self.assertEqual(OK, check_path_lang(*SKILL_OK, RULES)[0])

    def test_path_with_no_language_directory_is_refused(self):
        self.assertNotEqual(OK, check_path_lang("README.md", "kab", RULES)[0])


class TestCli(unittest.TestCase):
    def test_a_bad_path_exits_one(self):
        self.assertEqual(1, check_main(
            [ISSUE_564[0], "--lang", ISSUE_564[1], "--rules-file", RULES_FILE]))

    def test_a_good_path_exits_zero(self):
        self.assertEqual(0, check_main(
            [SKILL_OK[0], "--lang", SKILL_OK[1], "--rules-file", RULES_FILE]))

    def test_a_missing_rules_file_is_a_setup_error_not_a_bad_path(self):
        """The workflow labels the issue on exit 1 and writes no comment, so
        a moved rules file must never reach that branch: every submission,
        the correct ones included, would be labelled for a platform fault."""
        self.assertEqual(SETUP_ERROR, check_main(
            [SKILL_OK[0], "--lang", SKILL_OK[1], "--rules-file", "/nonexistent/rules.json"]))

    def test_a_rules_file_that_is_not_the_table_is_a_setup_error(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps({"languages": ["fr-FR"]}), encoding="utf-8")
            self.assertEqual(SETUP_ERROR, check_main(
                [SKILL_OK[0], "--lang", SKILL_OK[1], "--rules-file", str(path)]))

    def test_the_setup_error_code_is_neither_pass_nor_refusal(self):
        self.assertNotIn(SETUP_ERROR, (0, 1))


if __name__ == "__main__":
    unittest.main()
