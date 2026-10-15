"""The daily refresh turns red when the intents export fails.

``ovos-localize-export-intents`` refuses to write a corpus that disagrees with
the CSV or whose train and test splits overlap. With ``continue-on-error`` on
its step that refusal ended the run green, and nobody saw that nothing had
been published.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/update_data.yml"


def _steps() -> dict:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["generate"]["steps"]
    return {s["id"]: s for s in steps if "id" in s}, steps


def test_a_failed_export_fails_the_run():
    by_id, _ = _steps()
    export = by_id["export_intents"]
    assert "ovos-localize-export-intents" in export["run"]
    assert "continue-on-error" not in export


def test_the_publish_still_runs_only_on_a_good_export():
    """The step after the export reads its outcome, which a failure now also
    reports to the run."""
    _, steps = _steps()
    (publish,) = [s for s in steps if "publish_hf_dataset.py" in s.get("run", "")]
    assert "steps.export_intents.outcome == 'success'" in publish["if"]
