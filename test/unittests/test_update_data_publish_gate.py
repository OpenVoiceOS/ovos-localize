"""The browse publish commits a finished data build or nothing.

``generate_data.py`` writes each skill's file as it scans it and the
aggregates after the loop, so a build that dies part way leaves a tree that
is neither the previous data nor the new. "Publish browse data" commits
``data/**``. It must still run when only the locale table step fails, and
never after a failed or cancelled data build.

The step's ``if:`` is evaluated here on each combination of outcomes.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/update_data.yml"


def _steps() -> list:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["generate"]["steps"]


def _step(name: str) -> dict:
    (step,) = [s for s in _steps() if s.get("name") == name]
    return step


def _runs(outcomes: dict) -> bool:
    """Whether "Publish browse data" runs, given the earlier steps' outcomes.

    A step with no ``if:`` runs on ``success()``, which is false once any
    earlier step failed.
    """
    expr = _step("Publish browse data").get("if", "success()")
    expr = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", expr.strip())
    expr = expr.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
    expr = expr.replace("success()", repr(all(v == "success" for v in outcomes.values())))
    expr = re.sub(r"steps\.(\w+)\.outcome", lambda m: repr(outcomes.get(m.group(1), "")), expr)
    assert re.fullmatch(r"[\sA-Za-z_'\"!=()\-]*", expr), f"unexpected expression: {expr}"
    return bool(eval(expr, {"__builtins__": {}}))  # noqa: S307 - the alphabet is checked above


def test_the_data_build_has_the_id_the_condition_reads():
    assert _step("Generate data").get("id") == "generate_data"


@pytest.mark.parametrize("generate, table, expected", [
    ("success", "success", True),
    ("success", "failure", True),
    ("failure", "skipped", False),
    ("cancelled", "skipped", False),
])
def test_the_browse_publish_follows_the_data_build(generate, table, expected):
    assert _runs({"generate_data": generate, "locale_table": table}) is expected
