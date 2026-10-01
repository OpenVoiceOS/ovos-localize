"""The workflow's commit step, run against a real target checkout.

A submission whose text the target branch already holds stages nothing, and
``git commit`` on an empty index exits non-zero. The commit step reports that
case as ``already_shipped`` and exits 0, and the pull request step is skipped
on it (ovos-localize#695). This test runs the step's own shell, taken from the
workflow, in a throwaway clone with a local remote and a stub ``gh``, and then
evaluates the pull request step's ``if:`` on the outputs the step wrote.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = ROOT / ".github/workflows/submit_translation.yml"
FILE_PATH = "ovos_skill_laugh/locale/kab/vocab/laugh.voc"
SHIPPED = "ḍeṣ\nsserreḥ-as d ttaḍṣa\n"


def _steps() -> dict:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["create-pr"]["steps"]
    return {s.get("id"): s for s in steps}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, timeout=30).stdout.strip()


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """A checkout of the target branch whose kab file already holds SHIPPED."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(remote)], check=True, timeout=30)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True,
                   capture_output=True, timeout=30)
    path = work / FILE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(SHIPPED, encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
    _git(work, "push", "-q", "origin", "HEAD:dev")
    return work


def _run_commit_step(work: Path, tmp_path: Path, content: str) -> tuple[subprocess.CompletedProcess, dict]:
    step = _steps()["commit"]
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(exist_ok=True)
    gh = stub_bin / "gh"
    gh.write_text("#!/bin/sh\necho 0123456789abcdef0123456789abcdef01234567\n", encoding="utf-8")
    gh.chmod(0o755)
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    env = {
        "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(output),
        "GH_TOKEN": "fake", "ORG": "OpenVoiceOS", "REPO": "ovos-skill-laugh", "BASE": "dev",
        "FILE_PATH": FILE_PATH, "LANG": "kab", "FILE_KEY": "laugh.voc", "AUTHOR": "someone",
        "CONTENT_B64": base64.b64encode(content.encode()).decode(),
    }
    # The runner's own invocation of a run: block.
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                            cwd=work, env=env, capture_output=True, text=True, timeout=60)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return result, outputs


def _pr_step_runs(outputs: dict) -> bool:
    """Evaluate the pull request step's ``if:`` after a successful commit step.

    A step with no ``if:`` runs on success, which is the defect this guards.
    """
    expr = _steps()["pr"].get("if", "success()")
    expr = re.sub(r"^\$\{\{\s*|\s*\}\}$", "", expr.strip())
    expr = expr.replace("success()", "True").replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"steps\.commit\.outputs\.(\w+)", lambda m: repr(outputs.get(m.group(1), "")), expr)
    assert re.fullmatch(r"[\sA-Za-z_'\"!=()\-]*", expr), f"unexpected expression: {expr}"
    return bool(eval(expr, {"__builtins__": {}}))  # noqa: S307 - the alphabet is checked above


def test_text_already_on_the_branch_is_not_a_failure(target, tmp_path):
    result, outputs = _run_commit_step(target, tmp_path, SHIPPED)
    assert result.returncode == 0, result.stdout + result.stderr
    assert outputs.get("already_shipped") == "true"
    assert outputs.get("landed_sha") == "0123456789abcdef0123456789abcdef01234567"
    assert "branch_name" not in outputs
    assert _git(target, "ls-remote", "--heads", "origin", "translate/*") == ""


def test_no_pull_request_is_opened_for_text_already_shipped(target, tmp_path):
    _, outputs = _run_commit_step(target, tmp_path, SHIPPED)
    assert not _pr_step_runs(outputs)


def test_new_text_is_committed_pushed_and_opens_a_pull_request(target, tmp_path):
    result, outputs = _run_commit_step(target, tmp_path, SHIPPED + "ttaḍṣa\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "already_shipped" not in outputs
    assert outputs["branch_name"].startswith("translate/kab/laugh.voc-")
    assert _git(target, "ls-remote", "--heads", "origin", outputs["branch_name"]) != ""
    assert _pr_step_runs(outputs)
