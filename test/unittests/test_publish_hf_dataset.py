"""Unit tests for .github/scripts/publish_hf_dataset.py.

The script must never touch the network at import time: importing it used to
call HfApi().upload_folder()/upload_file() at module scope, so a plain
``import`` triggered a real publish. These tests pin that guarantee down and
exercise the pure CSV builder in isolation.
"""

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path

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
        '"intent": "check_weather.intent", "text": "what is the weather"}\n'
        '{"file_type": "voc", "lang": "en-us", "skill": "weather", '
        '"intent": "yes.voc", "text": "yes"}\n',
        encoding="utf-8",
    )
    module.CLASSIFICATION_DIR = classification_dir

    out_path = tmp_path / "ovos_localize_intents.csv"
    row_count = module.build_flat_csv(out_path)

    assert row_count == 1
    with out_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["lang", "domain", "intent", "sentence"]
    assert rows[1:] == [["en-us", "weather", "check_weather.intent", "what is the weather"]]


def _run_main_with_remote(monkeypatch, module, tmp_path, remote_files):
    from huggingface_hub import HfApi

    captured = {}
    monkeypatch.setattr(HfApi, "list_repo_files", lambda self, **kwargs: remote_files)
    monkeypatch.setattr(HfApi, "create_commit", lambda self, **kwargs: captured.update(kwargs))
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    module.CLASSIFICATION_DIR = tmp_path / "classification"
    module.main()
    return captured["operations"]


def test_publish_deletes_stale_corpus_tree(monkeypatch, tmp_path):
    """A data/datasets/ tree left in the dataset repo goes in the same commit as the CSV."""
    module = _load_module()
    operations = _run_main_with_remote(monkeypatch, module, tmp_path, [
        "data/datasets/classification/en-US.jsonl",
        "data/datasets/tts/en-US.jsonl",
        "README.md",
        "ovos_localize_intents.csv",
        ".gitattributes",
    ])

    from huggingface_hub import CommitOperationAdd, CommitOperationDelete

    added = [op.path_in_repo for op in operations if isinstance(op, CommitOperationAdd)]
    deleted = [(op.path_in_repo, op.is_folder) for op in operations
               if isinstance(op, CommitOperationDelete)]
    assert added == ["ovos_localize_intents.csv"]
    assert deleted == [("data/datasets/", True)]


def test_publish_without_stale_tree_only_uploads_csv(monkeypatch, tmp_path):
    module = _load_module()
    operations = _run_main_with_remote(monkeypatch, module, tmp_path, [
        "README.md",
        "ovos_localize_intents.csv",
        ".gitattributes",
    ])

    assert [op.path_in_repo for op in operations] == ["ovos_localize_intents.csv"]


def test_main_refuses_without_hf_token(monkeypatch, capsys):
    module = _load_module()

    class ExplodingHfApi:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HfApi must not be instantiated without HF_TOKEN")

    monkeypatch.setattr(module, "HfApi", ExplodingHfApi)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    module.main()

    assert "HF_TOKEN" in capsys.readouterr().out


def _capture_publish(monkeypatch, module, tmp_path):
    """Run main() offline and return every row it would publish, by source file."""
    from huggingface_hub import HfApi

    published_files = []

    def fake_upload_folder(self, folder_path, path_in_repo, **kwargs):
        for path in Path(folder_path).rglob("*"):
            if path.is_file():
                published_files.append(path)

    def fake_upload_file(self, path_or_fileobj, path_in_repo, **kwargs):
        published_files.append(Path(path_or_fileobj))

    def fake_create_commit(self, operations, **kwargs):
        for op in operations:
            if hasattr(op, "path_or_fileobj"):
                published_files.append(Path(op.path_or_fileobj))

    monkeypatch.setattr(HfApi, "upload_folder", fake_upload_folder)
    monkeypatch.setattr(HfApi, "upload_file", fake_upload_file)
    monkeypatch.setattr(HfApi, "create_commit", fake_create_commit)
    monkeypatch.setattr(HfApi, "list_repo_files", lambda self, **kwargs: [])
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    module.main()

    sources = set()
    for path in published_files:
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as f:
                sources.update(row["intent"] for row in csv.DictReader(f))
        elif path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    sources.add(row.get("intent") or row.get("dialog") or row.get("file_name"))
    return published_files, sources


def test_published_dataset_holds_intent_rows_only(monkeypatch, tmp_path):
    """A skill with every resource kind publishes rows from its .intent file only."""
    sys.path.insert(0, str(SCRIPT_PATH.parents[2] / "scripts"))
    import generate_data
    import generate_datasets

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

    datasets_dir = tmp_path / "data" / "datasets"
    monkeypatch.setattr(generate_datasets, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(generate_datasets, "DATASETS_DIR", datasets_dir)
    generate_datasets.main()

    module = _load_module()
    module.LOCAL_DIR = str(datasets_dir)
    module.CLASSIFICATION_DIR = datasets_dir / "classification"

    published_files, sources = _capture_publish(monkeypatch, module, tmp_path)

    assert published_files
    assert sources == {"foo.intent"}, f"published rows from {sorted(sources)}"
