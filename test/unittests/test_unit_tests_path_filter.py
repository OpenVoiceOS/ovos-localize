"""Every workflow file a unit test reads triggers the unit tests.

Several tests read a workflow or a script under ``.github`` and check what it
does. ``unit_tests.yml`` runs only on the paths it lists, so a pull request that
changes only one of those files ran none of the tests written for it, and
merged with nothing checked.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
UNIT_TESTS = ROOT / ".github/workflows/unit_tests.yml"
# This file names workflow files as glob examples, not because it reads them.
TESTS = sorted(p for p in (ROOT / "test" / "unittests").glob("test_*.py") if p.name != Path(__file__).name)


def _filters() -> dict[str, list[str]]:
    workflow = yaml.safe_load(UNIT_TESTS.read_text())
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    return {event: triggers[event]["paths"] for event in ("push", "pull_request")}


def _glob_to_regex(pattern: str) -> re.Pattern:
    """GitHub's path filter glob: ``**`` crosses directories, ``*`` does not."""
    out = ""
    for token in re.split(r"(\*\*/?|\*)", pattern):
        if token in ("**", "**/"):
            out += ".*"
        elif token == "*":
            out += "[^/]*"
        else:
            out += re.escape(token)
    return re.compile(out + r"\Z")


def _read_by_tests() -> list[str]:
    """Files under .github/workflows and .github/scripts that a unit test names."""
    text = "\n".join(path.read_text(encoding="utf-8") for path in TESTS)
    files = [p for d in ("workflows", "scripts") for p in sorted((ROOT / ".github" / d).iterdir()) if p.is_file()]
    return [p.relative_to(ROOT).as_posix() for p in files if p.name in text]


def test_some_test_reads_a_workflow_file():
    """Guards the check below against passing on an empty list."""
    assert ".github/workflows/submit_translation.yml" in _read_by_tests()


@pytest.mark.parametrize("event", ["push", "pull_request"])
@pytest.mark.parametrize("path", _read_by_tests())
def test_the_unit_tests_run_when_a_file_they_read_changes(event, path):
    patterns = _filters()[event]
    assert any(_glob_to_regex(p).match(path) for p in patterns), f"{path} is not in the {event} paths"


@pytest.mark.parametrize("pattern, path, expected", [
    (".github/scripts/**", ".github/scripts/publish_hf_dataset.py", True),
    ("scripts/**", ".github/scripts/publish_hf_dataset.py", False),
    ("ovos_localize/**", "ovos_localize/cli/validate.py", True),
    (".github/workflows/unit_tests.yml", ".github/workflows/update_data.yml", False),
])
def test_the_glob_reads_like_github(pattern, path, expected):
    assert bool(_glob_to_regex(pattern).match(path)) is expected
