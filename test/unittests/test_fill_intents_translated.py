import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from fill_intents_translated import (  # noqa: E402
    State,
    expand,
    load_published,
    load_sources,
    locale_summary,
    main,
    plan,
    run_locale,
)


class FakeHop:
    def __init__(self, model_id, src, tgt):
        self.model_id, self.src, self.tgt = model_id, src, tgt


class FakeRoute:
    def __init__(self, hops):
        self.hops = hops


class UpperTranslator:
    """Prefixes the text with ``tr `` and counts calls; a mask token survives as-is.

    The expansion step lowercases, so the marker is a word, not a case change.
    """

    def __init__(self):
        self.calls = []

    def route(self, src, tgt):
        return FakeRoute([FakeHop(f"fake-{src}-{tgt}", src, tgt)])

    def translate(self, text, src=None, tgt=None):
        self.calls.append(text)
        return "tr " + text


class NoRouteTranslator(UpperTranslator):
    def route(self, src, tgt):
        raise RuntimeError(f"no route {src}->{tgt}")


def _skill(path, skill_id, files):
    """Write one parsed-skill JSON with the given {intent: {lang: [lines]}}."""
    data = {"id": skill_id, "files": {}}
    for fname, langs in files.items():
        data["files"][fname] = {
            "type": "intent",
            "langs": {
                lang: {"entries": [{"line": i + 1, "text": t} for i, t in enumerate(lines)]}
                for lang, lines in langs.items()
            },
        }
    path.write_text(json.dumps(data), encoding="utf-8")


def _skills_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    _skill(d / "a.json", "skill-a", {
        "hello.intent": {"en-US": ["hello", "(hi|hey) there"], "de-DE": ["hallo"]},
        "time.intent": {"en-US": ["what time is it in {location}"]},
        "empty.intent": {"en-US": [], "de-DE": ["x"]},
        "note.dialog": {"en-US": ["not an intent"]},
    })
    _skill(d / "b.json", "skill-b", {
        "bye.intent": {"en-US": ["# comment", "goodbye"], "de-DE": []},
    })
    return d


def test_load_sources_keeps_intents_with_en_us_lines_only(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    assert set(src) == {("skill-a", "hello.intent"), ("skill-a", "time.intent"),
                        ("skill-b", "bye.intent")}
    assert src[("skill-b", "bye.intent")]["lines"] == ["goodbye"]
    # A locale with an empty entry list has no translation.
    assert src[("skill-b", "bye.intent")]["have"] == {"en-US"}
    assert src[("skill-a", "hello.intent")]["have"] == {"en-US", "de-DE"}


def test_plan_separates_human_published_and_remaining(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    published = {"de-DE": {
        ("skill-a", "time.intent"): 3,          # covers a gap: done
        ("skill-a", "hello.intent"): 5,         # human locale exists now: superseded
        ("skill-a", "gone.intent"): 2,          # no longer in en-US: stale
    }}
    t = plan(src, published, ["de-DE", "fr-FR"])
    de = t["de-DE"]
    assert de["gap_intents"] == 2
    assert de["published_gap_intents"] == 1
    assert de["remaining_intents"] == 1
    assert de["_remaining"] == [("skill-b", "bye.intent")]
    assert de["published_superseded_by_human"] == 1
    assert de["published_rows_superseded"] == 5
    assert de["published_stale_not_in_en_US"] == 1
    assert de["published_rows_stale"] == 2
    fr = t["fr-FR"]
    assert fr["gap_intents"] == fr["remaining_intents"] == 3
    assert fr["remaining_templates"] == 4


def test_load_published_counts_rows_per_locale_and_intent(tmp_path):
    p = tmp_path / "pub.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lang", "domain", "intent", "sentence"])
        w.writerow(["de-DE", "s", "a.intent", "eins"])
        w.writerow(["de-DE", "s", "a.intent", "zwei"])
        w.writerow(["fr-FR", "s", "a.intent", "un"])
    pub = load_published(p)
    assert pub["de-DE"][("s", "a.intent")] == 2
    assert pub["fr-FR"][("s", "a.intent")] == 1
    assert load_published(None) == {}


def test_expand_dedupes_and_cleans():
    assert sorted(expand(["(hi|hey) there", "Hi there"])) == ["hey there", "hi there"]


def test_run_locale_checkpoints_rows_and_keeps_slots(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    state = State(tmp_path / "state", "fr-FR")
    tx = UpperTranslator()
    remaining = plan(src, {}, ["fr-FR"])["fr-FR"]["_remaining"]
    assert run_locale(tx, "fr-FR", src, remaining, state) is True

    rows = state.committed_rows()
    sentences = {r["sentence"] for r in rows}
    assert "tr what time is it in {location}" in sentences
    assert all(r["lang"] == "fr-FR" for r in rows)
    assert {r["intent"] for r in rows} == {"hello.intent", "time.intent", "bye.intent"}
    # The slot name never reached the model.
    assert not any("{location}" in c or "location" in c.lower() for c in tx.calls)

    summary = locale_summary(state)
    assert summary["intents_filled"] == 3
    assert summary["templates_in"] == 4
    assert summary["templates_out"] == 4
    assert summary["sentences_out"] == len(rows) == 5


def test_run_locale_resumes_and_skips_checkpointed_intents(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    state = State(tmp_path / "state", "fr-FR")
    remaining = plan(src, {}, ["fr-FR"])["fr-FR"]["_remaining"]
    run_locale(UpperTranslator(), "fr-FR", src, remaining, state)

    # A second run against a fresh State on the same dir makes no model call.
    state2 = State(tmp_path / "state", "fr-FR")
    tx = UpperTranslator()
    run_locale(tx, "fr-FR", src, remaining, state2)
    assert tx.calls == []
    assert len(state2.committed_rows()) == 5


def test_half_written_intent_is_redone(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    # Rows on disk with no checkpoint marker: the shape a kill mid-intent leaves.
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "fr-FR.jsonl").write_text(
        json.dumps({"lang": "fr-FR", "domain": "skill-b",
                    "intent": "bye.intent", "sentence": "stale"}) + "\n", encoding="utf-8")
    state = State(tmp_path / "state", "fr-FR")
    assert state.committed_rows() == []
    remaining = [("skill-b", "bye.intent")]
    run_locale(UpperTranslator(), "fr-FR", src, remaining, state)
    rows = state.committed_rows()
    assert [r["sentence"] for r in rows] == ["tr goodbye"]
    # The orphan is gone from disk too, not only filtered on read.
    assert "stale" not in state.rows.read_text(encoding="utf-8")


def test_duplicate_copies_of_a_pair_collapse_on_read(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    state = State(tmp_path / "state", "fr-FR")
    run_locale(UpperTranslator(), "fr-FR", src, [("skill-b", "bye.intent")], state)
    # A second copy of the same rows, as a state dir from before orphan
    # purging can hold.
    with state.rows.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"lang": "fr-FR", "domain": "skill-b",
                            "intent": "bye.intent", "sentence": "tr goodbye"}) + "\n")
    assert [r["sentence"] for r in state.committed_rows()] == ["tr goodbye"]


def test_no_route_skips_the_locale_and_writes_nothing(tmp_path):
    src = load_sources(_skills_dir(tmp_path))
    state = State(tmp_path / "state", "xx-XX")
    remaining = plan(src, {}, ["xx-XX"])["xx-XX"]["_remaining"]
    assert run_locale(NoRouteTranslator(), "xx-XX", src, remaining, state) is None
    assert not state.rows.exists()
    assert state.data["done"] == {}


def test_export_writes_csv_and_manifest_and_drops_stale_published_rows(tmp_path, capsys):
    skills = _skills_dir(tmp_path)
    pub = tmp_path / "pub.csv"
    with pub.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lang", "domain", "intent", "sentence"])
        w.writerow(["de-DE", "skill-a", "time.intent", "wie spät ist es in {location}"])  # gap: kept
        w.writerow(["de-DE", "skill-a", "hello.intent", "hallo"])                       # human now: dropped
        w.writerow(["de-DE", "skill-a", "gone.intent", "weg"])                          # stale: dropped
    state_dir = tmp_path / "state"
    src = load_sources(skills)
    state = State(state_dir, "de-DE")
    run_locale(UpperTranslator(), "de-DE", src, [("skill-b", "bye.intent")], state)

    out = tmp_path / "out"
    rc = main(["--skills-dir", str(skills), "--published", str(pub), "--state-dir",
               str(state_dir), "--lang", "de-DE", "--export", "--out", str(out)])
    assert rc == 0
    with (out / "ovos_localize_intents_translated.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [(r["intent"], r["sentence"]) for r in rows] == [
        ("time.intent", "wie spät ist es in {location}"),
        ("bye.intent", "tr goodbye"),
    ]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["totals"] == {"published_rows_kept": 1, "new_rows": 1, "rows": 2}
    de = manifest["locales"]["de-DE"]
    assert de["published_rows_superseded"] == 1
    assert de["published_rows_stale"] == 1
    assert de["intents_filled"] == 1
    assert de["remaining_after_run"] == 0
    assert "_remaining" not in de


def test_status_prints_the_plan_without_a_translator(tmp_path, capsys):
    skills = _skills_dir(tmp_path)
    rc = main(["--skills-dir", str(skills), "--state-dir", str(tmp_path / "s"),
               "--lang", "fr-FR", "--status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "en-US intents: 3" in out
    assert "fr-FR: gaps=3 published=0 (0 rows) remaining=3 templates=4 checkpointed=0" in out
