"""The submitted path, placed in the target branch as it stands.

The fixture is ovos-skill-laugh after its #133: every language holds
``vocab/stop.voc``, and the re-run of ovos-localize#489 still carried
``kab/vocab/Stop.voc``, the name of the day it was submitted. That re-run
opened ovos-skill-laugh#137, a file the skill never loads.

ovos-localize#490 carries the key ``Laugh.intent`` with the path
``kab/vocab/Laugh.voc``: intent phrases bound for the keyword file.
"""
import contextlib
import io
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from ovos_localize.cli.resolve_target_path import StalePathError, main, resolve_target_path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/submit_translation.yml"

LOCALE = "ovos_skill_laugh/locale"
ISSUE_489 = (f"{LOCALE}/kab/vocab/Stop.voc", "Stop.voc")
ISSUE_490 = (f"{LOCALE}/kab/vocab/Laugh.voc", "Laugh.intent")


def _laugh_after_133(root: Path) -> None:
    for lang in ("en-US", "de-DE", "pt-PT"):
        for rel in ("vocab/laugh.voc", "vocab/laugh.intent", "vocab/stop.voc", "dialog/cancel.dialog",
                    "word_connectors.json"):
            f = root / LOCALE / lang / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x\n", encoding="utf-8")


class TestResolve(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _laugh_after_133(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_renamed_resource_takes_its_current_name(self):
        self.assertEqual(f"{LOCALE}/kab/vocab/stop.voc", resolve_target_path(ISSUE_489[0], self.root, ISSUE_489[1]))

    def test_a_key_of_another_resource_kind_is_refused(self):
        """#490's intent phrases must not become keywords of laugh.voc."""
        with self.assertRaises(StalePathError):
            resolve_target_path(ISSUE_490[0], self.root, ISSUE_490[1])

    def test_the_key_suffix_is_compared_ignoring_case(self):
        path = f"{LOCALE}/kab/vocab/laugh.voc"
        self.assertEqual(path, resolve_target_path(path, self.root, "Laugh.VOC"))

    def test_a_json_resource_is_not_held_to_its_key_suffix(self):
        path = f"{LOCALE}/kab/word_connectors.json"
        self.assertEqual(path, resolve_target_path(path, self.root, "word_connectors.resource_json"))

    def test_a_current_resource_for_a_new_language_is_unchanged(self):
        path = f"{LOCALE}/kab/dialog/cancel.dialog"
        self.assertEqual(path, resolve_target_path(path, self.root))

    def test_an_existing_file_is_unchanged(self):
        path = f"{LOCALE}/de-DE/vocab/stop.voc"
        self.assertEqual(path, resolve_target_path(path, self.root))

    def test_a_removed_resource_is_refused(self):
        with self.assertRaises(StalePathError):
            resolve_target_path(f"{LOCALE}/kab/vocab/giggle.voc", self.root)

    def test_a_removed_locale_root_is_refused(self):
        with self.assertRaises(StalePathError):
            resolve_target_path("skill_laugh/locale/kab/vocab/laugh.voc", self.root)

    def test_two_spellings_are_refused_not_guessed(self):
        other = self.root / LOCALE / "fr-FR" / "vocab" / "STOP.voc"
        other.parent.mkdir(parents=True)
        other.write_text("x\n", encoding="utf-8")
        with self.assertRaises(StalePathError):
            resolve_target_path(ISSUE_489[0], self.root)

    def test_the_cli_prints_the_path_to_write(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, main([ISSUE_489[0], "--file-key", ISSUE_489[1], "--repo-root", str(self.root)]))
        self.assertEqual(f"{LOCALE}/kab/vocab/stop.voc", out.getvalue().strip())

    def test_the_cli_exits_one_on_a_key_of_another_kind(self):
        self.assertEqual(1, main([ISSUE_490[0], "--file-key", ISSUE_490[1], "--repo-root", str(self.root)]))

    def test_the_cli_exits_one_on_a_removed_resource(self):
        self.assertEqual(1, main([f"{LOCALE}/kab/vocab/giggle.voc", "--repo-root", str(self.root)]))


class TestWorkflowWritesTheResolvedPath(unittest.TestCase):
    """The resolver is only a fix if the steps that write and announce the
    file read its answer instead of the issue's path."""

    @classmethod
    def setUpClass(cls):
        steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["create-pr"]["steps"]
        cls.all_steps = steps
        cls.steps = {s.get("id"): s for s in steps}

    def test_the_resolver_runs_on_the_target_checkout(self):
        run = self.steps["target"]["run"]
        self.assertIn("ovos-localize-resolve-target-path", run)
        self.assertIn('--file-key "$FILE_KEY"', run)
        self.assertEqual("${{ steps.parse.outputs.file_key }}", self.steps["target"]["env"]["FILE_KEY"])

    def test_commit_and_pr_steps_use_the_resolved_path(self):
        for step_id in ("commit", "pr"):
            self.assertEqual("${{ steps.target.outputs.file_path }}",
                             self.steps[step_id]["env"]["FILE_PATH"], step_id)

    def test_the_closing_note_names_the_written_file(self):
        (close,) = [s for s in self.all_steps if s.get("name") == "Close the submission"]
        self.assertEqual("${{ steps.target.outputs.file_path }}", close["env"]["FILE_PATH"])

    def test_branch_commit_and_title_are_named_after_the_written_file(self):
        """FILE_KEY names the branch, the commit subject and the title."""
        for step_id in ("commit", "pr"):
            self.assertEqual("${{ steps.target.outputs.file_key }}",
                             self.steps[step_id]["env"]["FILE_KEY"], step_id)
        self.assertIn('file_key=$(basename "$RESOLVED")', self.steps["target"]["run"])

    def test_no_writing_step_reads_the_issue_path(self):
        for step_id in ("commit", "pr"):
            step = self.steps[step_id]
            text = step["run"] + "".join(map(str, step["env"].values()))
            self.assertIsNone(re.search(r"steps\.parse\.outputs\.file_(path|key)", text), step_id)
