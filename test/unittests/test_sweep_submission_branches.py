"""The sweep command and the workflow gate that decides whether it deletes.

The gate is not read here, it is run: the shell that turns the workflow's
APPLY value into the `--apply` flag is taken out of the workflow file and
executed on the three values GitHub passes it. A scheduled run deletes, a
dispatched run deletes only when it was asked to, and a dispatched run that
was not asked only reports.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import pytest
import yaml

from ovos_localize.cli.sweep_submission_branches import gh_api, main

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github/workflows/sweep_submission_branches.yml"


def _apply_gate() -> str:
    """The `if` that turns APPLY into the flag, taken from the workflow."""
    text = WORKFLOW.read_text()
    match = re.search(
        r'FLAGS=""\n\s*(?P<gate>if \[ "\$APPLY" = [^\n]+\n\s*FLAGS="--apply"\n\s*fi)',
        text,
    )
    assert match, "the --apply gate was not found in the workflow"
    return re.sub(r"^\s+", "", match.group("gate"), flags=re.M)


@pytest.mark.parametrize("apply_value,expected", [
    ("yes", "--apply"),    # a scheduled run
    ("true", "--apply"),   # dispatched with the apply box ticked
    ("false", ""),         # dispatched without it
    ("", ""),              # dispatched on a workflow that passed nothing
])
def test_the_workflow_gate_turns_apply_into_the_flag(apply_value, expected):
    script = f'{_apply_gate()}\nprintf "%s" "$FLAGS"\n'
    result = subprocess.run(
        ["bash", "-c", script],
        env={"APPLY": apply_value, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=True,
    )
    assert result.stdout == expected


class TestWorkflow:
    def test_the_workflow_parses_and_runs_on_a_schedule_and_on_demand(self):
        spec = yaml.safe_load(WORKFLOW.read_text())
        triggers = spec[True] if True in spec else spec["on"]
        assert "schedule" in triggers
        assert "workflow_dispatch" in triggers
        assert triggers["workflow_dispatch"]["inputs"]["apply"]["default"] is False

    def test_a_scheduled_run_resolves_apply_to_yes(self):
        text = WORKFLOW.read_text()
        assert "github.event_name == 'schedule' && 'yes' || inputs.apply" in text

    def test_the_repository_list_excludes_archived_and_private_repositories(self):
        text = WORKFLOW.read_text()
        assert "select(.archived == false)" in text
        assert "select(.private == false)" in text


class TestGhApi:
    def _run(self, stdout, returncode=0, stderr=""):
        completed = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr,
        )
        return patch("subprocess.run", return_value=completed)

    def test_a_paginated_read_flattens_the_pages_into_one_list(self):
        pages = json.dumps([[{"name": "a"}, {"name": "b"}], [{"name": "c"}]])
        with self._run(pages):
            assert [{"name": "a"}, {"name": "b"}, {"name": "c"}] == gh_api("repos/o/r/branches", paginate=True)

    def test_a_paginated_read_uses_slurp_so_the_pages_stay_parseable(self):
        with self._run("[[]]") as mocked:
            gh_api("repos/o/r/branches", paginate=True)
        command = mocked.call_args[0][0]
        assert "--paginate" in command
        assert "--slurp" in command

    def test_query_parameters_are_encoded_into_the_url(self):
        with self._run("[]") as mocked:
            gh_api("repos/o/r/pulls", params={"state": "all", "head": "o:translate/kab/a.voc-1"})
        url = mocked.call_args[0][0][-1]
        assert url == "repos/o/r/pulls?state=all&head=o%3Atranslate%2Fkab%2Fa.voc-1"

    def test_a_missing_resource_raises_lookup_error(self):
        with self._run("", returncode=1, stderr="gh: Not Found (HTTP 404)"):
            with pytest.raises(LookupError):
                gh_api("repos/o/r/contents/gone.voc")

    def test_a_refusal_whose_body_carries_the_digits_404_is_still_a_refusal(self):
        # Read as a missing resource, a refused delete is recorded as nothing
        # wrong and the branch is left without a reason.
        with self._run(
            "", returncode=1,
            stderr='gh: Validation Failed (HTTP 422) {"ref":"translate/kab/error404.voc-1"}',
        ):
            with pytest.raises(RuntimeError):
                gh_api("repos/o/r/git/refs/heads/translate/kab/error404.voc-1", method="DELETE")

    def test_a_refused_call_raises_runtime_error(self):
        with self._run("", returncode=1, stderr="HTTP 403: protected branch"):
            with pytest.raises(RuntimeError, match="protected branch"):
                gh_api("repos/o/r/git/refs/heads/x", method="DELETE")

    def test_an_empty_body_reads_as_an_empty_object(self):
        with self._run(""):
            assert {} == gh_api("repos/o/r/git/refs/heads/x", method="DELETE")

    def test_a_delete_passes_the_method_through(self):
        with self._run("") as mocked:
            gh_api("repos/o/r/git/refs/heads/x", method="DELETE")
        command = mocked.call_args[0][0]
        assert command[:4] == ["gh", "api", "--method", "DELETE"]


def _routes(owner, repo, branches, pulls_by_branch, default_branch="dev"):
    routes = {
        f"repos/{owner}/{repo}/branches": [{"name": name} for name in branches],
        f"repos/{owner}/{repo}": {"default_branch": default_branch},
    }
    for branch, pulls in pulls_by_branch.items():
        params = {"state": "all", "head": f"{owner}:{branch}"}
        routes[f"repos/{owner}/{repo}/pulls?{json.dumps(params, sort_keys=True)}"] = pulls
    return routes


class RecordingApi:
    def __init__(self, routes, refuse=()):
        self.routes = routes
        self.refuse = set(refuse)
        self.deleted = []

    def __call__(self, path, params=None, paginate=False, method="GET"):
        path = unquote(path)
        if method == "DELETE":
            if path in self.refuse:
                raise RuntimeError("protected ref")
            self.deleted.append(path)
            return {}
        key = f"{path}?{json.dumps(params, sort_keys=True)}" if params else path
        if key not in self.routes:
            raise LookupError(f"not found: {key}")
        return self.routes[key]


class TestMain:
    def test_a_dry_run_reports_the_counts_and_deletes_nothing(self, capsys):
        merged = {"number": 161, "state": "closed", "merged_at": "2026-08-26T12:54:40Z"}
        api = RecordingApi(_routes(
            "OpenVoiceOS", "ovos-skill-alerts",
            ["dev", "translate/kab/all_day.voc-1787734123"],
            {"translate/kab/all_day.voc-1787734123": [merged]},
        ))
        status = main(
            ["--owner", "OpenVoiceOS", "--no-compare-content", "ovos-skill-alerts"],
            api=api,
        )
        out = capsys.readouterr().out
        assert status == 0
        assert api.deleted == []
        assert "1 submission branches found, 1 finished, 0 still needed." in out
        assert "0 deleted: this was a dry run. 1 would be deleted." in out
        assert "Re-run with --apply to delete them." in out

    def test_apply_deletes_and_says_so(self, capsys):
        merged = {"number": 161, "state": "closed", "merged_at": "2026-08-26T12:54:40Z"}
        branch = "translate/kab/all_day.voc-1787734123"
        api = RecordingApi(_routes("o", "r", [branch], {branch: [merged]}))
        status = main(["--owner", "o", "--apply", "--no-compare-content", "r"], api=api)
        out = capsys.readouterr().out
        assert status == 0
        assert api.deleted == [f"repos/o/r/git/refs/heads/{branch}"]
        assert "1 deleted, 0 refused." in out
        assert "Re-run with --apply" not in out

    def test_a_refused_delete_exits_one_and_names_the_branch(self, capsys):
        merged = {"number": 161, "state": "closed", "merged_at": "2026-08-26T12:54:40Z"}
        branch = "translate/kab/all_day.voc-1787734123"
        api = RecordingApi(
            _routes("o", "r", [branch], {branch: [merged]}),
            refuse=[f"repos/o/r/git/refs/heads/{branch}"],
        )
        status = main(["--owner", "o", "--apply", "--no-compare-content", "r"], api=api)
        out = capsys.readouterr().out
        assert status == 1
        assert "0 deleted, 1 refused." in out
        assert f"[ERROR] could not delete o/r {branch}" in out

    def test_an_unreadable_repository_exits_one_and_sweeps_the_others(self, capsys):
        merged = {"number": 1, "state": "closed", "merged_at": "2026-08-26T12:54:40Z"}
        branch = "translate/kab/a.voc-1"
        api = RecordingApi(_routes("o", "good", [branch], {branch: [merged]}))
        status = main(
            ["--owner", "o", "--no-compare-content", "missing", "good"],
            api=api,
        )
        out = capsys.readouterr().out
        assert status == 1
        assert "[ERROR] could not sweep o/missing" in out
        assert "1 submission branches found, 1 finished, 0 still needed." in out

    def test_a_repository_with_nothing_to_sweep_exits_zero(self, capsys):
        api = RecordingApi(_routes("o", "r", ["dev", "main"], {}))
        status = main(["--owner", "o", "--no-compare-content", "r"], api=api)
        out = capsys.readouterr().out
        assert status == 0
        assert "0 submission branches found, 0 finished, 0 still needed." in out
        assert "Re-run with --apply" not in out

    def test_an_open_pull_request_survives_an_applied_sweep(self, capsys):
        opened = {"number": 135, "state": "open", "merged_at": None}
        branch = "translate/kab/Laugh.intent-1790867113"
        api = RecordingApi(_routes("o", "ovos-skill-laugh", [branch], {branch: [opened]}))
        status = main(
            ["--owner", "o", "--apply", "--no-compare-content", "ovos-skill-laugh"],
            api=api,
        )
        out = capsys.readouterr().out
        assert status == 0
        assert api.deleted == []
        assert "1 submission branches found, 0 finished, 1 still needed." in out
