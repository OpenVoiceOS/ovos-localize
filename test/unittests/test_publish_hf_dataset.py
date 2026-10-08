"""Unit tests for .github/scripts/publish_hf_dataset.py.

The script must never touch the network at import time: importing it used to
call HfApi().upload_folder()/upload_file() at module scope, so a plain
``import`` triggered a real publish. These tests pin that guarantee down and
check the commit each dataset repo receives, with the Hub calls captured.
"""

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path

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


def _run_main_with_remote(monkeypatch, module, tmp_path, remotes):
    """Run main() offline; return the operations of each commit, by repo id."""
    from huggingface_hub import HfApi

    captured = {}
    monkeypatch.setattr(HfApi, "list_repo_files", lambda self, repo_id, **kwargs: remotes[repo_id])
    monkeypatch.setattr(HfApi, "create_commit",
                        lambda self, repo_id, operations, **kwargs: captured.update({repo_id: operations}))
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("INTENTS_EXPORT_DIR", str(_export_dir(tmp_path)))
    module.main()
    return captured


def _paths(operations):
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete

    added = [op.path_in_repo for op in operations if isinstance(op, CommitOperationAdd)]
    deleted = [(op.path_in_repo, op.is_folder) for op in operations if isinstance(op, CommitOperationDelete)]
    return added, deleted


def test_publish_deletes_stale_corpus_tree(monkeypatch, tmp_path):
    """A data/datasets/ tree left in the CSV dataset repo goes in the same commit as the CSV."""
    module = _load_module()
    captured = _run_main_with_remote(monkeypatch, module, tmp_path, {
        module.CSV_REPO_ID: ["data/datasets/classification/en-US.jsonl", "data/datasets/tts/en-US.jsonl",
                             "README.md", "ovos_localize_intents.csv", ".gitattributes"],
        module.CORPUS_REPO_ID: [],
    })

    assert _paths(captured[module.CSV_REPO_ID]) == (["ovos_localize_intents.csv"], [("data/datasets/", True)])


def test_publish_without_stale_tree_only_uploads_csv(monkeypatch, tmp_path):
    module = _load_module()
    captured = _run_main_with_remote(monkeypatch, module, tmp_path, {
        module.CSV_REPO_ID: ["README.md", "ovos_localize_intents.csv", ".gitattributes"],
        module.CORPUS_REPO_ID: [],
    })

    assert _paths(captured[module.CSV_REPO_ID]) == (["ovos_localize_intents.csv"], [])


def test_corpus_publish_replaces_the_split_files_in_full(monkeypatch, tmp_path):
    """Every remote file the export did not write is deleted, except .gitattributes."""
    module = _load_module()
    captured = _run_main_with_remote(monkeypatch, module, tmp_path, {
        module.CSV_REPO_ID: [],
        module.CORPUS_REPO_ID: [".gitattributes", "README.md", "manifest.json", "en-US/train_templates.jsonl",
                                "en-US/test.jsonl", "arb/train_templates.jsonl"],
    })

    added, deleted = _paths(captured[module.CORPUS_REPO_ID])
    assert added == ["README.md", "en-US/test.jsonl", "en-US/train.jsonl", "manifest.json"]
    assert deleted == [("arb/train_templates.jsonl", False), ("en-US/train_templates.jsonl", False)]


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


def test_main_refuses_without_hf_token(monkeypatch, capsys):
    module = _load_module()

    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated without HF_TOKEN")

    monkeypatch.setattr(module, "HfApi", ExplodingHfApi)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    module.main()

    assert "HF_TOKEN" in capsys.readouterr().out


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


def _repository_not_found():
    from types import SimpleNamespace

    from huggingface_hub.errors import RepositoryNotFoundError

    response = SimpleNamespace(status_code=404, headers={}, text="", content=b"", json=dict, request=None)
    return RepositoryNotFoundError("404 Client Error: repository not found", response=response)


def test_missing_csv_repo_does_not_stop_the_corpus_publish(monkeypatch, tmp_path, capsys):
    """A Hub 404 on the CSV repo is reported and fails the run, after the corpus repo is published."""
    from huggingface_hub import HfApi

    module = _load_module()
    committed = {}

    def list_repo_files(self, repo_id, **kwargs):
        if repo_id == module.CSV_REPO_ID:
            raise _repository_not_found()
        return []

    monkeypatch.setattr(HfApi, "list_repo_files", list_repo_files)
    monkeypatch.setattr(HfApi, "create_commit",
                        lambda self, repo_id, operations, **kwargs: committed.update({repo_id: operations}))
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("INTENTS_EXPORT_DIR", str(_export_dir(tmp_path)))

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code not in (0, None)
    assert list(committed) == [module.CORPUS_REPO_ID]
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith(f"published {module.CORPUS_REPO_ID}: 4 files added, 0 deleted")
    assert out[1].startswith(f"FAILED {module.CSV_REPO_ID}: RepositoryNotFoundError: 404 Client Error")


def test_failed_corpus_repo_does_not_stop_the_csv_publish(monkeypatch, tmp_path, capsys):
    from huggingface_hub import HfApi

    module = _load_module()
    committed = {}

    def create_commit(self, repo_id, operations, **kwargs):
        if repo_id == module.CORPUS_REPO_ID:
            raise RuntimeError("boom")
        committed[repo_id] = operations

    monkeypatch.setattr(HfApi, "list_repo_files", lambda self, repo_id, **kwargs: [])
    monkeypatch.setattr(HfApi, "create_commit", create_commit)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("INTENTS_EXPORT_DIR", str(_export_dir(tmp_path)))

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code not in (0, None)
    assert list(committed) == [module.CSV_REPO_ID]
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"FAILED {module.CORPUS_REPO_ID}: RuntimeError: boom"
    assert out[1].startswith(f"published {module.CSV_REPO_ID}:")
