"""The editor's choice between a key-and-value form and a free-line textarea.

T-4500. `index.html` decides with `isJsonFile`. It used to test the file's
type against a list of three names, and `word_connectors.json` is indexed as
type ``word_connectors``, after its own name, so it missed the list: the
translator got a free-line box for a flat JSON object and typed one value per
line. That payload is ``ovos-workshop#659`` — ``d`` and ``naɣ`` over a file
whose keys are ``and`` and ``or``.

The assertions live in ``test/js/json_form_detection.test.js`` because the
predicate is JavaScript and the test reads it out of ``index.html`` rather
than keeping a second copy that can drift. This module is what makes the repo
test suite run it.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
JS_TEST = REPO / "test" / "js" / "json_form_detection.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_editor_picks_the_json_form_by_the_file_s_own_data():
    result = subprocess.run(
        ["node", str(JS_TEST)],
        capture_output=True, text=True, cwd=str(REPO), timeout=120,
    )
    assert result.returncode == 0, (
        "the editor's JSON-form detection regressed:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_the_predicate_is_still_in_the_page():
    """A guard for the skip above: if node is missing on a runner, the test
    above is silent, so this one still fails when the predicate is gone."""
    page = (REPO / "index.html").read_text(encoding="utf-8")
    assert "looksLikeJsonResource" in page, (
        "index.html no longer carries the JSON-form predicate this suite tests"
    )
