"""Unit tests for .github/scripts/publish_hf_dataset.py.

The script must never touch the network at import time: importing it used to
call HfApi().upload_folder()/upload_file() at module scope, so a plain
``import`` triggered a real publish. These tests pin that guarantee down and
exercise the pure CSV builder in isolation.
"""

import csv
import importlib.util
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


def test_build_flat_csv_keeps_only_intent_rows(tmp_path):
    module = _load_module()

    classification_dir = tmp_path / "data" / "datasets" / "classification"
    classification_dir.mkdir(parents=True)
    (classification_dir / "sample.jsonl").write_text(
        '{"file_type": "intent", "lang": "en-us", "skill": "weather", '
        '"intent": "check_weather", "text": "what is the weather"}\n'
        '{"file_type": "voc", "lang": "en-us", "skill": "weather", '
        '"intent": "yes", "text": "yes"}\n',
        encoding="utf-8",
    )
    module.CLASSIFICATION_DIR = classification_dir

    out_path = tmp_path / "ovos_localize_intents.csv"
    row_count = module.build_flat_csv(out_path)

    assert row_count == 1
    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["lang", "domain", "intent", "sentence"]
    assert rows[1:] == [["en-us", "weather", "check_weather", "what is the weather"]]


def test_delete_patterns_prune_stale_corpus_files_only(monkeypatch, tmp_path):
    """delete_patterns must be relative to path_in_repo.

    HfApi._prepare_folder_deletions strips path_in_repo from each remote
    filename before matching delete_patterns against it (see
    huggingface_hub.hf_api), so a pattern of "data/datasets/**" never
    matches anything once path_in_repo is already "data/datasets". This
    captures the actual delete_patterns argument the script passes to
    upload_folder (without letting upload_folder touch the network) and
    replays it through the real (offline) deletion-planning helper, to
    prove a removed corpus file is pruned while root-level files (which
    never enter the candidate set: the helper only considers files whose
    repo-root path starts with path_in_repo) are left untouched.
    """
    module = _load_module()

    classification_dir = tmp_path / "data" / "datasets" / "classification"
    classification_dir.mkdir(parents=True)
    (classification_dir / "new.jsonl").write_text("", encoding="utf-8")
    module.LOCAL_DIR = str(tmp_path / "data" / "datasets")
    module.CLASSIFICATION_DIR = classification_dir

    from huggingface_hub import HfApi

    captured = {}

    def fake_upload_folder(self, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(HfApi, "upload_folder", fake_upload_folder)
    monkeypatch.setattr(HfApi, "upload_file", lambda self, **kwargs: None)
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    module.main()

    assert "delete_patterns" in captured
    delete_patterns = captured["delete_patterns"]

    monkeypatch.setattr(HfApi, "list_repo_files", lambda self, **kwargs: [
        "data/datasets/classification/old.jsonl",
        "data/datasets/classification/new.jsonl",
        "README.md",
        "ovos_localize_intents.csv",
        ".gitattributes",
    ])

    api = HfApi(token="fake")
    ops = api._prepare_folder_deletions(
        repo_id=module.REPO_ID,
        repo_type="dataset",
        revision=None,
        path_in_repo=module.PATH_IN_REPO,
        delete_patterns=delete_patterns,
    )
    deleted = {op.path_in_repo for op in ops}

    assert "data/datasets/classification/old.jsonl" in deleted, (
        "stale corpus file must be a delete candidate; the old "
        f"delete_patterns={delete_patterns!r} matches nothing because it "
        "is repo-root-relative instead of relative to path_in_repo"
    )
    assert "README.md" not in deleted
    assert "ovos_localize_intents.csv" not in deleted


def test_main_refuses_without_hf_token(monkeypatch, capsys):
    module = _load_module()

    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated without HF_TOKEN")

    monkeypatch.setattr(module, "HfApi", ExplodingHfApi)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    module.main()

    assert "HF_TOKEN" in capsys.readouterr().out
