"""The workflow's own .json gate, executed (T-4548).

`is_json_resource` lowercases the whole path, so it is case-insensitive. The
workflow gate decides the same question in shell, and it read
`case "$FILE_PATH" in *.json|*.JSON)`, which is case-insensitive for two
spellings out of many: `word_connectors.Json` went to the raw write, which is
the ovos-workshop#659 defect again.

This test does not read the gate, it runs it, on the spellings that matter.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from ovos_localize.sync.json_resource import is_json_resource

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github/workflows/submit_translation.yml"

SPELLINGS = [
    "ovos_workshop/locale/kab/word_connectors.json",
    "ovos_workshop/locale/kab/word_connectors.JSON",
    "ovos_workshop/locale/kab/word_connectors.Json",
    "ovos_workshop/locale/kab/word_connectors.jSoN",
]
NOT_JSON = [
    "ovos_workshop/locale/kab/and.voc",
    "ovos_workshop/locale/kab/dialog.json.voc",
    "ovos_workshop/locale/kab/jsonish",
]


def _gate_source() -> str:
    """The `case` head the write step uses, taken from the workflow itself."""
    text = WORKFLOW.read_text()
    m = re.search(r'^\s*case "(?P<subject>[^"]+)" in\s*\n\s*(?P<pattern>\*[^)]*)\)',
                  text, re.M)
    assert m, "the .json gate was not found in the workflow"
    return m.group("subject"), m.group("pattern")


def _gate_says_json(path: str) -> bool:
    subject, pattern = _gate_source()
    script = (f'FILE_PATH={path!r}\n'
              f'case "{subject}" in\n'
              f'  {pattern}) echo json ;;\n'
              f'  *) echo other ;;\n'
              f'esac\n')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         timeout=10)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip() == "json"


@pytest.mark.parametrize("path", SPELLINGS)
def test_the_gate_catches_every_spelling_of_json(path) -> None:
    assert _gate_says_json(path), path


@pytest.mark.parametrize("path", NOT_JSON)
def test_the_gate_lets_a_line_resource_through(path) -> None:
    assert not _gate_says_json(path), path


@pytest.mark.parametrize("path", SPELLINGS + NOT_JSON)
def test_the_gate_and_the_predicate_agree(path) -> None:
    """One question, two implementations: they must answer the same."""
    assert _gate_says_json(path) == is_json_resource(path), path
