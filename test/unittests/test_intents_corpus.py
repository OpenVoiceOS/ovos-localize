"""Tests for the intents corpus export and the skill data it reads.

Expected values are written out by hand from the fixtures, never read back
from the code under test.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import generate_data  # noqa: E402
import generate_datasets  # noqa: E402

from ovos_localize.corpus import labels  # noqa: E402
from ovos_localize.corpus.export import check_equivalence, export, failures  # noqa: E402
from ovos_localize.corpus.source import classify_commit, line_provenance, read_skill_source  # noqa: E402
from ovos_localize.datasets.skill_files import load_skills  # noqa: E402

SKILL_PYPROJECT = """[project]
name = "ovos-skill-lamp"

[project.entry-points."opm.skill"]
"ovos-skill-lamp.openvoiceos" = "ovos_skill_lamp:LampSkill"
"""

PLUGIN_PYPROJECT = """[project]
name = "ovos-lamp-pipeline-plugin"

[project.entry-points."opm.pipeline"]
"ovos-lamp-pipeline" = "ovos_lamp:LampPipeline"
"""


def _git(repo: Path, *args: str, author: str = "Dev <dev@example.com>") -> None:
    name, email = author[:-1].split(" <")
    subprocess.run(
        ["git", "-C", str(repo), "-c", f"user.name={name}", "-c", f"user.email={email}", *args],
        check=True, capture_output=True,
    )


def _write(repo: Path, files: dict) -> None:
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _commit(repo: Path, files: dict, message: str, author: str = "Dev <dev@example.com>") -> None:
    _write(repo, files)
    _git(repo, "add", "-A", author=author)
    _git(repo, "commit", "-q", "-m", message, author=author)


def _init(repo: Path) -> Path:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    return repo


def _scan_to_skills_dir(repo: Path, org: str, name: str, skills_dir: Path) -> dict:
    scan = generate_data.RepoScanner(str(repo.parent / "unused")).scan(str(repo))
    skill = generate_data.build_skill_json(scan, org, name)
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / f"{name}.json").write_text(json.dumps(skill), encoding="utf-8")
    return skill


@pytest.fixture
def fleet(tmp_path: Path) -> Path:
    """A skill and a plugin, scanned into a data/skills directory."""
    skills_dir = tmp_path / "data" / "skills"

    skill = _init(tmp_path / "repos" / "ovos-skill-lamp")
    _commit(skill, {
        "pyproject.toml": SKILL_PYPROJECT,
        "ovos_skill_lamp/locale/en-us/turn_on.intent": "turn on the <lamp> in the {room}\n",
        "ovos_skill_lamp/locale/en-us/lamp.voc": "lamp\nlight\n",
        "ovos_skill_lamp/locale/en-us/room.entity": "kitchen\n",
        "ovos_skill_lamp/locale/en-us/dim.intent": "dim to {level}\n",
        "ovos_skill_lamp/locale/en-us/laugh.voc": "haha\n",
        "ovos_skill_lamp/locale/en-us/laugh.intent": "make me laugh\n",
        "test/end2end/golden_utterances.jsonl":
            json.dumps({"utterance": "turn on the lamp in the kitchen", "intent_label": "turn_on.intent",
                        "lang": "en-US"}) + "\n",
    }, "feat: lamp skill")
    _commit(skill, {
        "ovos_skill_lamp/locale/pt-pt/turn_on.intent": "liga a luz\n",
    }, "translate(pt-PT): update turn_on.intent", author="ovos-localize[bot] <bot@example.com>")
    _commit(skill, {
        "ovos_skill_lamp/locale/de-de/turn_on.intent": "schalte das licht ein\n",
    }, "locale: draft de-DE from en-US (machine translation, unvouched)\n\nEngine: linguonnx",
        author="ovos-bot <bot@example.com>")
    _scan_to_skills_dir(skill, "OpenVoiceOS", "ovos-skill-lamp", skills_dir)

    plugin = _init(tmp_path / "repos" / "ovos-lamp-pipeline-plugin")
    _commit(plugin, {
        "pyproject.toml": PLUGIN_PYPROJECT,
        "ovos_lamp/locale/en-us/lamp_query.intent": "is the lamp on\n",
    }, "feat: plugin")
    _scan_to_skills_dir(plugin, "OpenVoiceOS", "ovos-lamp-pipeline-plugin", skills_dir)
    return skills_dir


def _read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestSkillFiles:
    """A chunked skill is one skill, never one per chunk."""

    def test_generate_datasets_labels_chunk_rows_with_the_skill(self, tmp_path: Path, monkeypatch) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        intent = {"type": "intent", "langs": {"en-US": {"entries": [{"line": 1, "text": "tell me more"}],
                                                        "file_path": "locale/en-us/more.intent"}}}
        (skills_dir / "ovos-skill-split.json").write_text(json.dumps({
            "id": "ovos-skill-split", "repo": "OpenVoiceOS/ovos-skill-split", "files": {},
            "chunks": ["ovos-skill-split_0.json"],
        }))
        (skills_dir / "ovos-skill-split_0.json").write_text(json.dumps({"files": {"more.intent": intent}}))

        datasets_dir = tmp_path / "datasets"
        monkeypatch.setattr(generate_datasets, "SKILLS_DIR", skills_dir)
        monkeypatch.setattr(generate_datasets, "DATASETS_DIR", datasets_dir)
        generate_datasets.main()

        rows = _read_jsonl(datasets_dir / "classification" / "en-US.jsonl")
        assert [(r["skill"], r["intent"], r["text"]) for r in rows] == [
            ("ovos-skill-split", "more.intent", "tell me more")]

    def test_orphan_chunk_is_not_a_skill(self, tmp_path: Path) -> None:
        (tmp_path / "ovos-skill-a.json").write_text(json.dumps({"repo": "o/ovos-skill-a", "files": {}}))
        (tmp_path / "ovos-skill-a_3.json").write_text(json.dumps({"files": {"x.intent": {}}}))
        assert [skill_id for skill_id, _ in load_skills(tmp_path)] == ["ovos-skill-a"]


class TestPruneStaleSkillFiles:
    def test_unwritten_files_go_and_failed_repos_keep_their_last_scan(self, tmp_path: Path) -> None:
        for name in ("kept.json", "dropped.json", "split.json", "split_0.json", "split_1.json",
                     "failed.json", "failed_0.json"):
            (tmp_path / name).write_text("{}")
        (tmp_path / "failed.json").write_text(json.dumps({"chunks": ["failed_0.json"]}))

        removed = generate_data.prune_stale_skill_files(
            tmp_path, {"kept.json", "split.json", "split_0.json"}, ["failed"])

        assert removed == ["dropped.json", "split_1.json"]
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "failed.json", "failed_0.json", "kept.json", "split.json", "split_0.json"]


class TestBuildSkillJson:
    def test_same_base_name_of_two_types_keeps_both_files(self, fleet: Path) -> None:
        files = json.loads((fleet / "ovos-skill-lamp.json").read_text())["files"]
        assert [e["text"] for e in files["laugh.intent"]["langs"]["en-US"]["entries"]] == ["make me laugh"]
        assert [e["text"] for e in files["laugh.voc"]["langs"]["en-US"]["entries"]] == ["haha"]

    def test_corpus_fields_come_from_the_clone(self, fleet: Path) -> None:
        skill = json.loads((fleet / "ovos-skill-lamp.json").read_text())
        plugin = json.loads((fleet / "ovos-lamp-pipeline-plugin.json").read_text())
        assert skill["skill_id"] == "ovos-skill-lamp.openvoiceos"
        assert skill["entry_points"] == ["opm.skill"]
        assert len(skill["commit"]) == 40
        assert [g["path"] for g in skill["golden"]] == ["test/end2end/golden_utterances.jsonl"]
        assert plugin["skill_id"] is None
        assert plugin["entry_points"] == ["opm.pipeline"]


class TestProvenance:
    def test_classify_commit(self) -> None:
        assert classify_commit("translate(kab): update x.intent", "") == ("native", None)
        assert classify_commit("locale: draft fa-IR (machine translation, unvouched)",
                               "locale: draft fa-IR (machine translation, unvouched)\n\nvia agentpipe") == (
            "machine_translation", "agentpipe")
        assert classify_commit("feat(locale): machine draft of fa-IR", "feat(locale): machine draft of fa-IR") == (
            "machine_translation", "unrecorded")
        assert classify_commit("feat: add oc-FR locale", "feat: add oc-FR locale") == ("unknown", None)

    #: Submission subjects whose commit says a machine wrote the line, with the engine each names.
    MACHINE_SUBJECTS = [
        ("translate(kab): agentpipe draft", "agentpipe"),
        ("translate(kab): agentpipe-generated draft", "agentpipe"),
        ("translate(de): deepl output", "deepl"),
        ("translate(de): via nllb", "nllb"),
        ("translate(fr): opus-mt pass", "opus-mt"),
        ("translate(fr): opus mt pass", "opus-mt"),
        ("translate(pt): google translate rough pass", "google translate"),
        ("translate(pt): Google-Translate rough pass", "google translate"),
        ("translate(ca): linguonnx lines", "linguonnx"),
        ("translate(gl): marian output", "marian"),
        ("translate(eu): argos pass", "argos"),
        ("translate(oc): libretranslate pass", "libretranslate"),
        ("translate(it): llm-generated lines", "unrecorded"),
        ("translate(es): generated by an LLM", "unrecorded"),
        ("translate(nl): MT draft", "unrecorded"),
        ("translate(pl): translated automatically", "unrecorded"),
        ("translate(pl): automatically translated lines", "unrecorded"),
        ("translate(cs): bot output, please check", "unrecorded"),
        ("translate(sv): synthetic lines", "unrecorded"),
        ("translate(da): machine translated", "unrecorded"),
        ("translate(fi): AI-generated lines", "unrecorded"),
        ("translate(hu): auto-translated", "unrecorded"),
    ]

    #: Real submission subjects of the fleet, each with the message ovos-localize writes.
    NATIVE_SUBJECTS = [
        "translate(kab): update skill.json",
        "translate(kab): update fuster_lifespan.intent",
        "translate(kab): update lifespan.dialog",
        "translate(kab-DZ): update world_news.voc (#144)",
        "translate(kab-DZ): update global_news.intent (#146)",
        "translate(da-dk): phase 2 - all 34 dataset training templates (#69)",
        "translate(ca-ES,cs-CZ,es-ES,eu-ES,gl-ES,hu-HU,it-IT,lt-LT,pl-PL,ru-RU,sv-SE): "
        "fill missing en-US basenames (#102)",
        "translate(de-DE): update a.intent",
        "translate(mt-MT): update weather.intent",
        "translate(pt-BR): update translate.intent",
        "translate(it-IT): update generate_password.intent",
    ]

    @pytest.mark.parametrize(("subject", "engine"), MACHINE_SUBJECTS)
    def test_a_commit_that_says_machine_is_never_native(self, subject: str, engine: str) -> None:
        native_message = "Submitted by @someone via OVOS Localize"
        assert classify_commit(subject, f"{subject}\n\n{native_message}") == ("machine_translation", engine)
        assert classify_commit(subject, "") == ("machine_translation", engine)
        neutral = "translate(de): add missing condition lines"
        assert classify_commit(neutral, f"{neutral}\n\n{subject.split(': ', 1)[1]}") == (
            "machine_translation", engine)

    @pytest.mark.parametrize("subject", NATIVE_SUBJECTS)
    def test_a_submission_that_names_no_machine_is_native(self, subject: str) -> None:
        for author in ("someone", "marian-k", "openvoiceos-bot", "deepl_fan"):
            message = f"{subject}\n\nSubmitted by @{author} via OVOS Localize"
            assert classify_commit(subject, message) == ("native", None)

    def test_each_line_takes_the_commit_that_last_wrote_it(self, tmp_path: Path) -> None:
        repo = _init(tmp_path / "r")
        _commit(repo, {"a.intent": "one\ntwo\n"}, "feat: add")
        _commit(repo, {"a.intent": "one\nzwei\n"}, "translate(de-DE): update a.intent")
        assert line_provenance(repo, "a.intent", {}) == {1: ("unknown", None), 2: ("native", None)}

    def test_setup_py_skill_is_a_skill(self, tmp_path: Path) -> None:
        repo = _init(tmp_path / "ovos-skill-old")
        _commit(repo, {"setup.py": (
            'URL = "https://github.com/OpenVoiceOS/ovos-skill-old"\n'
            'SKILL_CLAZZ = "OldSkill"\n'
            'AUTHOR, SKILL_NAME = URL.split(".com/")[-1].split("/")\n'
            'SKILL_ID = f"{SKILL_NAME.lower()}.{AUTHOR.lower()}"\n'
            'PLUGIN_ENTRY_POINT = f"{SKILL_ID}=ovos_skill_old:{SKILL_CLAZZ}"\n'
            'setup(entry_points={"ovos.plugin.skill": PLUGIN_ENTRY_POINT})\n')}, "feat: setup")
        source = read_skill_source(repo, "ovos-skill-old")
        assert source["entry_points"] == ["ovos.plugin.skill"]
        assert source["skill_id"] == "ovos-skill-old.openvoiceos"


class TestEquivalence:
    ROWS = [
        ("en-US", "ovos-skill-lamp", "turn_on.intent", "turn on the lamp"),
        ("en-US", "ovos-skill-lamp", "dim.intent", "dim it"),
        ("en-US", "ovos-lamp-pipeline-plugin", "lamp_query.intent", "is the lamp on"),
    ]
    SKILLS = {"ovos-skill-lamp": "ovos-skill-lamp.openvoiceos"}
    EXCLUDED = {"ovos-lamp-pipeline-plugin": "plugin"}
    PAIRS = {("ovos-skill-lamp.openvoiceos", "turn_on"), ("ovos-skill-lamp.openvoiceos", "dim")}

    def test_equal_sets_pass(self) -> None:
        result = check_equivalence(self.PAIRS, self.ROWS, self.SKILLS, self.EXCLUDED)
        assert result["equal"] is True
        assert (result["pairs_corpus"], result["pairs_csv"]) == (2, 2)

    def test_a_pair_missing_from_the_corpus_fails(self) -> None:
        result = check_equivalence({("ovos-skill-lamp.openvoiceos", "turn_on")}, self.ROWS, self.SKILLS,
                                   self.EXCLUDED)
        assert result["equal"] is False
        assert result["only_in_csv"] == ["ovos-skill-lamp.openvoiceos:dim"]
        assert failures({"equivalence": result, "train_rows": 1, "test_rows": 1,
                         "train_test_overlap_after_removal_exact": 0,
                         "train_test_overlap_after_removal_punct_insensitive": 0})

    def test_a_pair_missing_from_the_csv_fails(self) -> None:
        result = check_equivalence(self.PAIRS | {("ovos-skill-lamp.openvoiceos", "brighten")}, self.ROWS,
                                   self.SKILLS, self.EXCLUDED)
        assert result["equal"] is False
        assert result["only_in_corpus"] == ["ovos-skill-lamp.openvoiceos:brighten"]

    def test_a_csv_domain_nobody_accounts_for_fails(self) -> None:
        rows = self.ROWS + [("en-US", "ovos-skill-lamp_0", "dim.intent", "dim it")]
        result = check_equivalence(self.PAIRS, rows, self.SKILLS, self.EXCLUDED)
        assert result["equal"] is False
        assert result["csv_domains_unaccounted"] == ["ovos-skill-lamp_0"]


class TestExport:
    def test_export(self, fleet: Path, tmp_path: Path) -> None:
        out = tmp_path / "out"
        manifest = export(fleet, out)

        train = {}
        for path in sorted((out / "ovos-intents").glob("*/train.jsonl")):
            for row in _read_jsonl(path):
                train.setdefault((row["lang"], row["label"]), []).append(row)
        assert sorted((k, sorted(r["utterance"] for r in v)) for k, v in train.items()) == [
            (("de-DE", "ovos-skill-lamp.openvoiceos:turn_on"), ["schalte das licht ein"]),
            (("en-US", "ovos-skill-lamp.openvoiceos:dim"), ["dim to {level}"]),
            (("en-US", "ovos-skill-lamp.openvoiceos:laugh"), ["make me laugh"]),
            # "turn on the lamp in the kitchen" is the golden utterance, so it left the train side.
            (("en-US", "ovos-skill-lamp.openvoiceos:turn_on"), ["turn on the light in the kitchen"]),
            (("pt-PT", "ovos-skill-lamp.openvoiceos:turn_on"), ["liga a luz"]),
        ]
        row = train[("de-DE", "ovos-skill-lamp.openvoiceos:turn_on")][0]
        assert (row["skill_id"], row["intent_name"], row["template"], row["source_repo"]) == (
            "ovos-skill-lamp.openvoiceos", "turn_on", "schalte das licht ein", "OpenVoiceOS/ovos-skill-lamp")
        assert row["source_file"] == "ovos_skill_lamp/locale/de-de/turn_on.intent"
        assert (row["provenance"], row["mt_engine"]) == ("machine_translation", "linguonnx")
        assert train[("pt-PT", "ovos-skill-lamp.openvoiceos:turn_on")][0]["provenance"] == "native"

        test = _read_jsonl(out / "ovos-intents" / "en-US" / "test.jsonl")
        assert [(r["label"], r["utterance"]) for r in test] == [
            ("ovos-skill-lamp.openvoiceos:turn_on", "turn on the lamp in the kitchen")]
        assert not (out / "ovos-intents" / "de-DE" / "test.jsonl").exists()

        with (out / "ovos_localize_intents.csv").open(encoding="utf-8", newline="") as fh:
            csv_rows = list(csv.reader(fh))
        assert csv_rows[0] == ["lang", "domain", "intent", "sentence"]
        assert {(d, i) for _, d, i, _ in csv_rows[1:]} == {
            ("ovos-skill-lamp", "turn_on.intent"), ("ovos-skill-lamp", "dim.intent"),
            ("ovos-skill-lamp", "laugh.intent"), ("ovos-lamp-pipeline-plugin", "lamp_query.intent")}

        assert manifest["equivalence"]["equal"] is True
        assert manifest["excluded_repositories"] == {
            "ovos-lamp-pipeline-plugin": "registers no ovos.plugin.skill entry point "
                                         "(entry point groups: opm.pipeline)"}
        assert (manifest["train_rows"], manifest["test_rows"], manifest["labels"], manifest["skills"]) == (5, 1, 3, 1)
        assert manifest["train_test_overlap_removed"] == 1
        assert manifest["train_test_overlap_after_removal_exact"] == 0
        assert manifest["train_test_overlap_after_removal_punct_insensitive"] == 0
        assert manifest["train_rows_with_a_literal_slot"] == 1
        assert manifest["labels_without_test_rows"] == [
            "ovos-skill-lamp.openvoiceos:dim", "ovos-skill-lamp.openvoiceos:laugh"]
        assert manifest["provenance_train"] == {"native": 1, "machine_translation": 1, "unknown": 3}
        assert failures(manifest) == []
        card = (out / "ovos-intents" / "README.md").read_text(encoding="utf-8")
        assert "| train rows | 5 |" in card
        assert "machine translation engines (train rows): linguonnx 1" in card

    def test_typed_slot_fills_from_the_parser_of_its_language(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        repo = _init(tmp_path / "repos" / "ovos-skill-timer")
        _commit(repo, {
            "pyproject.toml": SKILL_PYPROJECT.replace("lamp", "timer"),
            "locale/en-us/start.intent": "start a timer for {number:minutes} minutes\n",
        }, "feat: timer")
        _scan_to_skills_dir(repo, "OpenVoiceOS", "ovos-skill-timer", skills_dir)

        export(skills_dir, tmp_path / "out")

        rows = _read_jsonl(tmp_path / "out" / "ovos-intents" / "en-US" / "train.jsonl")
        assert sorted(r["utterance"] for r in rows) == sorted(
            f"start a timer for {n} minutes" for n in ("3", "three", "15", "fifteen", "42", "forty two"))

    def test_label_uses_the_entry_point_skill_id_not_the_repository(self) -> None:
        assert labels.label("skill-easter-eggs.openvoiceos", "joke.intent") == "skill-easter-eggs.openvoiceos:joke"
