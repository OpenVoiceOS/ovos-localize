"""Unit tests for .github/scripts/publish_hf_dataset.py.

The script must never touch the network at import time: importing it used to
call HfApi().upload_folder()/upload_file() at module scope, so a plain
``import`` triggered a real publish. These tests pin that guarantee down and
check the one commit the publish makes, with the Hub calls captured.
"""

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# These tests exercise HfApi against monkeypatched/offline code paths only;
# force huggingface_hub itself to refuse any real network access regardless
# of the environment the suite happens to run in.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "publish_hf_dataset.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("publish_hf_dataset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_performs_no_upload(monkeypatch):
    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated at import time")

    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "HfApi", ExplodingHfApi)
    sys.modules.pop("publish_hf_dataset", None)

    # Must not raise: the module only defines functions at import time.
    _load_module()


def _export_dir(tmp_path, corpus_files=("README.md", "manifest.json", "en-US/train.jsonl", "en-US/test.jsonl")):
    export_dir = tmp_path / "intents-export"
    export_dir.mkdir()
    (export_dir / "ovos_localize_intents.csv").write_text(
        "lang,domain,intent,sentence\nen-US,ovos-skill-lamp,dim.intent,dim it\n", encoding="utf-8")
    for name in corpus_files:
        path = export_dir / "ovos-intents" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    return export_dir


REMOTE_MAIN = [".gitattributes", "README.md", "manifest.json", "en-US/train_templates.jsonl",
               "en-US/test.jsonl", "arb/train_templates.jsonl", "data/datasets/tts/en-US.jsonl"]
FIRST_COMMIT = "0" * 40


class FakeHub:
    """The Hub as far as the publish may use it.

    Only the calls a branch publish needs exist. A delete, a tag, a folder
    upload or any other write is an AttributeError, so the test fails on it.
    """

    def __init__(self, fail_commit=None):
        self.calls = []
        self.fail_commit = fail_commit

    def list_repo_files(self, repo_id, **kwargs):
        self.calls.append(("list_repo_files", repo_id, kwargs))
        return list(REMOTE_MAIN)

    def list_repo_commits(self, repo_id, **kwargs):
        self.calls.append(("list_repo_commits", repo_id, kwargs))
        # Newest first, as the Hub lists them.
        return [SimpleNamespace(commit_id=sha)
                for sha in ("2" * 40, "1" * 40, FIRST_COMMIT)]

    def create_branch(self, repo_id, **kwargs):
        self.calls.append(("create_branch", repo_id, kwargs))

    def create_commit(self, repo_id, operations, **kwargs):
        self.calls.append(("create_commit", repo_id, dict(kwargs, operations=operations)))
        if self.fail_commit:
            raise self.fail_commit

    def commits(self):
        return [kwargs for name, _, kwargs in self.calls if name == "create_commit"]


def _run_main(monkeypatch, module, tmp_path, hub):
    monkeypatch.setattr(module, "HfApi", lambda token=None: hub)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("INTENTS_EXPORT_DIR", str(_export_dir(tmp_path)))
    module.main()
    return hub


def test_publish_never_deletes_a_file(monkeypatch, tmp_path):
    """The dataset is add-only: remote files the export did not write stay."""
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete

    module = _load_module()
    hub = _run_main(monkeypatch, module, tmp_path, FakeHub())

    operations = [op for commit in hub.commits() for op in commit["operations"]]
    deleted = [op.path_in_repo for op in operations if isinstance(op, CommitOperationDelete)]
    assert deleted == []
    assert all(isinstance(op, CommitOperationAdd) for op in operations)
    assert sorted(op.path_in_repo for op in operations) == [
        "README.md", "en-US/test.jsonl", "en-US/train.jsonl", "manifest.json"]


def test_publish_writes_the_branch_and_never_main(monkeypatch, tmp_path):
    module = _load_module()
    hub = _run_main(monkeypatch, module, tmp_path, FakeHub())

    assert {repo for _, repo, _ in hub.calls} == {"OpenVoiceOS/ovos-intents"}
    (commit,) = hub.commits()
    assert commit["revision"] == "localize-daily"
    branches = [kwargs for name, _, kwargs in hub.calls if name == "create_branch"]
    assert branches == [{"repo_type": "dataset", "branch": "localize-daily",
                         "revision": FIRST_COMMIT, "exist_ok": True}]
    names = [name for name, _, _ in hub.calls]
    assert names.index("create_branch") < names.index("create_commit")


def test_a_publish_failure_turns_the_run_red(monkeypatch, tmp_path):
    """The script exits non-zero on a Hub error, and the step does not swallow it."""
    module = _load_module()
    with pytest.raises(SystemExit) as exit_info:
        _run_main(monkeypatch, module, tmp_path, FakeHub(fail_commit=ConnectionError("Connection reset by peer")))
    assert exit_info.value.code not in (0, None)

    step = _publish_step()
    assert "continue-on-error" not in step
    assert step["run"].strip() == "python .github/scripts/publish_hf_dataset.py"


def _publish_step():
    import yaml

    workflow = yaml.safe_load((SCRIPT_PATH.parents[1] / "workflows" / "update_data.yml").read_text())
    (step,) = [s for job in workflow["jobs"].values() for s in job["steps"]
               if "publish_hf_dataset.py" in s.get("run", "")]
    return step


def _run_main_on_export(monkeypatch, module, export_dir):
    """Run main() on *export_dir* with a Hub that fails the test on any call."""
    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated for an export without rows")

    monkeypatch.setattr(module, "HfApi", ExplodingHfApi)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("INTENTS_EXPORT_DIR", str(export_dir))
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    return exit_info.value


@pytest.mark.parametrize("shape", ["missing", "empty_dir", "empty_corpus_files", "csv_header_only"])
def test_main_refuses_an_export_without_rows(monkeypatch, tmp_path, shape):
    """An export tree that holds no rows never reaches the Hub, so no remote file is deleted."""
    module = _load_module()
    export_dir = tmp_path / "intents-export"
    if shape == "empty_dir":
        export_dir.mkdir()
    elif shape == "empty_corpus_files":
        export_dir = _export_dir(tmp_path)
        for path in (export_dir / "ovos-intents").rglob("*.jsonl"):
            path.write_text("", encoding="utf-8")
    elif shape == "csv_header_only":
        export_dir = _export_dir(tmp_path)
        (export_dir / module.CSV_PATH_IN_REPO).write_text("lang,domain,intent,sentence\n", encoding="utf-8")

    error = _run_main_on_export(monkeypatch, module, export_dir)

    assert error.code not in (0, None)
    assert "refusing to publish" in str(error.code)
    assert str(export_dir) in str(error.code)


def test_main_refuses_without_hf_token(monkeypatch):
    """A missing secret is a failed publish, not a skipped one."""
    module = _load_module()

    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated without HF_TOKEN")

    monkeypatch.setattr(module, "HfApi", ExplodingHfApi)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code not in (0, None)
    assert "HF_TOKEN" in str(exit_info.value.code)


def test_published_csv_holds_intent_rows_only(tmp_path):
    """A skill with every resource kind exports CSV rows from its .intent file only."""
    sys.path.insert(0, str(SCRIPT_PATH.parents[2] / "scripts"))
    import generate_data

    from ovos_localize.corpus.export import export

    skill_dir = tmp_path / "ovos-skill-fixture"
    locale = skill_dir / "locale" / "en-us"
    locale.mkdir(parents=True)
    (locale / "foo.intent").write_text("turn on the (light|lamp)\n", encoding="utf-8")
    (locale / "bar.voc").write_text("lightbulb\n", encoding="utf-8")
    (locale / "baz.dialog").write_text("the light is on\n", encoding="utf-8")
    (locale / "qux.entity").write_text("kitchen\n", encoding="utf-8")

    scan = generate_data.RepoScanner(str(tmp_path / "repos")).scan(str(skill_dir))
    skill = generate_data.build_skill_json(scan, "OpenVoiceOS", "ovos-skill-fixture")
    skills_dir = tmp_path / "data" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / f"{skill['id']}.json").write_text(json.dumps(skill), encoding="utf-8")

    export(skills_dir, tmp_path / "out")

    with (tmp_path / "out" / "ovos_localize_intents.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["lang", "domain", "intent", "sentence"],
        ["en-US", "ovos-skill-fixture", "foo.intent", "turn on the lamp"],
        ["en-US", "ovos-skill-fixture", "foo.intent", "turn on the light"],
    ]
