"""Export the intents corpus and the flat intent CSV from one read of the skills.

The skill data ovos-localize keeps in ``data/skills/`` is the one source. Each
skill file is read once, and the same pass emits:

* the rows of ``ovos_localize_intents.csv``, the ``.intent`` rows of the
  classification export (``lang``, ``domain``, ``intent``, ``sentence``);
* the train rows of the intents corpus, each ``.intent`` line expanded and
  slot-filled with the resources of its own language;
* the test rows of the intents corpus, the skill's golden utterances at the
  same commit.

Equivalence therefore holds by construction, and the export proves it: the
``(skill_id, intent_name)`` pairs of the corpus must equal the pairs derived
from the CSV rows through the same label function, or the export fails.

Only skills enter the corpus. A repository whose packaging registers no
``ovos.plugin.skill`` entry point is a plugin or a library: it stays in the
CSV, and the manifest names it with the reason it is not in the corpus.

Train rows whose utterance matches a test utterance are removed from the train
side, compared after lowercasing, collapsing whitespace and stripping edge
punctuation. The manifest records the overlap left after the removal under the
exact and the punctuation-insensitive comparison, and both must be zero.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from ovos_localize.corpus import labels
from ovos_localize.corpus.expansion import (
    fill,
    has_bare_alternation,
    normalize_lang,
    normalize_utterance,
    normalize_utterance_punct_insensitive,
    split_bare_alternation,
)
from ovos_localize.corpus.gold import gold_rows
from ovos_localize.datasets.classification import generate_intent_classification
from ovos_localize.datasets.skill_files import load_skills

CSV_NAME = "ovos_localize_intents.csv"
CSV_COLUMNS = ("lang", "domain", "intent", "sentence")
INTENT_SUFFIX = ".intent"
CORPUS_DIR = "ovos-intents"
CORPUS_REPO_ID = "OpenVoiceOS/ovos-intents"
PROVENANCE_VALUES = ("native", "machine_translation", "llm", "unknown")
SLOT = re.compile(r"\{[^}]+\}")

#: Retired datasets whose role this corpus holds.
SUPERSEDES = (
    "ovos-intents-train-v1",
    "ovos-intents-train-latest",
    "ovos-intents-v5-eval",
    "ovos-golden-utterances-bench",
    "OVOSGitLocalize-Intents",
    "MT-intents-dataset-pt-PT",
    "ovos-llm-augmented-intents",
    "ovos-weather-intents",
    "ovos-common-query-intents",
    "ovos-intents-massive-subset",
    "ovos-intents-ilenia-testset-ca",
    "ovos-intents-ilenia-testset-es",
    "ovos-intents-ilenia-testset-nl",
)


def locale_dir_lang(file_path: str, locale_dir: str) -> str:
    """The language of a resource: its locale directory, case-folded only.

    OVOS-INTENT-2 §2 makes tag comparison case-insensitive, so ``fr-fr`` and
    ``fr-FR`` are one language. Nothing wider is folded: ``eu`` and ``eu-ES``
    stay distinct.
    """
    prefix = f"{locale_dir}/" if locale_dir else ""
    relative = file_path[len(prefix):] if prefix and file_path.startswith(prefix) else file_path
    return normalize_lang(relative.split("/", 1)[0])


def read_resources(data: dict, stats: collections.Counter) -> tuple:
    """Templates, slot hints and keywords of one skill, per language.

    Returns ``(templates, hints, keywords)``. A template is
    ``(lang, intent_name, line, source_file, provenance, mt_engine)``.
    """
    templates = []
    hints = collections.defaultdict(dict)
    keywords = collections.defaultdict(dict)
    locale_dir = data.get("locale_dir", "locale")
    for file_key, file_data in data["files"].items():
        kind = file_data["type"]
        if kind not in ("intent", "entity", "voc"):
            continue
        name = file_key[: -len(kind) - 1]
        for lang_data in file_data["langs"].values():
            lang = locale_dir_lang(lang_data["file_path"], locale_dir)
            lines = [e for e in lang_data["entries"]
                     if e["text"].strip() and not e["text"].strip().startswith("#")]
            if kind == "intent":
                for entry in lines:
                    line = entry["text"].strip()
                    # A `|` no group covers binds nothing the grammar defines,
                    # and the author's meaning cannot be recovered.
                    if has_bare_alternation(line):
                        stats["template_with_a_bare_alternation_dropped"] += 1
                        continue
                    templates.append((lang, name, line, lang_data["file_path"],
                                      entry["provenance"], entry.get("mt_engine")))
                continue
            # Two directories differing only in case are one language, so
            # their files are unioned rather than one replacing the other.
            target = (hints if kind == "entity" else keywords)[lang].setdefault(name.lower(), [])
            for entry in lines:
                for value in split_bare_alternation(entry["text"].strip()):
                    if value not in target:
                        target.append(value)
    return templates, hints, keywords


def check_equivalence(corpus_pairs: set, csv_rows: list, skill_ids: dict, excluded: dict) -> dict:
    """Compare the corpus pairs with the pairs the CSV rows derive.

    A CSV row derives ``(skill_id, intent_name)`` through the same label
    function as the corpus: the domain is mapped to the skill id its entry
    point declares, and the ``.intent`` suffix is dropped. Rows of an excluded
    repository derive nothing. A CSV domain that is neither a skill nor an
    excluded repository is a domain nobody can account for, and fails the
    check on its own.
    """
    csv_pairs = set()
    unaccounted = set()
    for _, domain, intent, _ in csv_rows:
        if domain in skill_ids:
            csv_pairs.add((skill_ids[domain], labels.intent_name(intent)))
        elif domain not in excluded:
            unaccounted.add(domain)
    only_corpus = sorted(":".join(p) for p in corpus_pairs - csv_pairs)
    only_csv = sorted(":".join(p) for p in csv_pairs - corpus_pairs)
    return {
        "equal": not only_corpus and not only_csv and not unaccounted,
        "pairs_corpus": len(corpus_pairs),
        "pairs_csv": len(csv_pairs),
        "only_in_corpus": only_corpus,
        "only_in_csv": only_csv,
        "csv_domains_unaccounted": sorted(unaccounted),
    }


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def export(skills_dir: Path, out_dir: Path) -> dict:
    """Write the CSV, the corpus tree and its manifest; return the manifest."""
    stats = collections.Counter()
    csv_rows = []
    skill_ids, excluded, skills = {}, {}, {}
    test = []
    corpus_dir = out_dir / CORPUS_DIR
    corpus_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="intents-export-") as scratch:
        raw_path = Path(scratch) / "train.raw.jsonl"
        seen = set()
        with raw_path.open("w", encoding="utf-8") as raw:
            for repo_name, data in load_skills(skills_dir):
                for sample in generate_intent_classification(repo_name, data):
                    if sample["intent"].endswith(INTENT_SUFFIX):
                        csv_rows.append((sample["lang"], sample["skill"], sample["intent"], sample["text"]))
                if "entry_points" not in data:
                    excluded[repo_name] = ("the skill file carries no entry point, commit or golden "
                                           "files: its last successful scan predates them")
                    continue
                if not data["skill_id"]:
                    groups = ", ".join(data["entry_points"]) or "none"
                    excluded[repo_name] = (f"registers no ovos.plugin.skill entry point "
                                           f"(entry point groups: {groups})")
                    continue
                skill_id = data["skill_id"]
                skill_ids[repo_name] = skill_id
                source = {"source_repo": data["repo"], "source_ref": data["commit"]}
                skills[skill_id] = {**source, "repository": repo_name,
                                    "entry_points": data["entry_points"]}
                templates, hints, keywords = read_resources(data, stats)
                for lang, name, template, source_file, provenance, mt_engine in templates:
                    label = labels.label(skill_id, name)
                    for sentence in fill(template, hints.get(lang, {}), keywords.get(lang, {}), stats, lang):
                        key = (label, lang, sentence.lower())
                        if key in seen:
                            stats["train_duplicate_rows_removed"] += 1
                            continue
                        seen.add(key)
                        raw.write(json.dumps({
                            "lang": lang, "label": label, "skill_id": skill_id,
                            "intent_name": name, "utterance": sentence,
                            "template": template, **source, "source_file": source_file,
                            "provenance": provenance, "mt_engine": mt_engine,
                        }, ensure_ascii=False) + "\n")
                for row in gold_rows(skill_id, data.get("golden", []), stats):
                    test.append({"lang": row["lang"], "label": row["label"],
                                 "skill_id": skill_id, "intent_name": row["intent_name"],
                                 "utterance": row["utterance"], **source,
                                 "source_file": row["source_file"],
                                 "provenance": row["provenance"], "mt_engine": None})
        del seen

        gold_exact = {normalize_utterance(r["utterance"]) for r in test}
        gold_wide = {normalize_utterance_punct_insensitive(r["utterance"]) for r in test}
        removed = overlap_exact = overlap_wide = literal_slot = 0
        corpus_pairs = set()
        train_langs = collections.Counter()
        provenance = collections.Counter()
        mt_engines = collections.Counter()
        writers = {}
        try:
            with raw_path.open(encoding="utf-8") as fh:
                for line in fh:
                    row = json.loads(line)
                    if normalize_utterance_punct_insensitive(row["utterance"]) in gold_wide:
                        removed += 1
                        continue
                    # Re-measured on the surviving rows, so the filter and the
                    # check can disagree.
                    overlap_exact += normalize_utterance(row["utterance"]) in gold_exact
                    overlap_wide += normalize_utterance_punct_insensitive(row["utterance"]) in gold_wide
                    literal_slot += bool(SLOT.search(row["utterance"]))
                    corpus_pairs.add((row["skill_id"], row["intent_name"]))
                    train_langs[row["lang"]] += 1
                    provenance[row["provenance"]] += 1
                    if row["mt_engine"]:
                        mt_engines[row["mt_engine"]] += 1
                    if row["lang"] not in writers:
                        path = corpus_dir / row["lang"] / "train.jsonl"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        writers[row["lang"]] = path.open("w", encoding="utf-8")
                    writers[row["lang"]].write(line)
        finally:
            for writer in writers.values():
                writer.close()

    test_by_lang = collections.defaultdict(list)
    for row in test:
        test_by_lang[row["lang"]].append(row)
    for lang, rows in test_by_lang.items():
        _write_jsonl(corpus_dir / lang / "test.jsonl", rows)

    csv_rows.sort()
    csv_path = out_dir / CSV_NAME
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(csv_rows)

    labels_trained = {f"{s}:{i}" for s, i in corpus_pairs}
    labels_scored = {r["label"] for r in test}
    equivalence = check_equivalence(corpus_pairs, csv_rows, skill_ids, excluded)
    manifest = {
        "corpus": CORPUS_REPO_ID,
        "train_rows": sum(train_langs.values()),
        "test_rows": len(test),
        "labels": len(labels_trained),
        "skills": len(skills),
        "languages_train": len(train_langs),
        "languages_test": len(test_by_lang),
        "labels_without_test_rows": sorted(labels_trained - labels_scored),
        "test_labels_without_train_rows": sorted(labels_scored - labels_trained),
        "train_rows_with_a_literal_slot": literal_slot,
        "train_test_overlap_removed": removed,
        "train_test_overlap_after_removal_exact": overlap_exact,
        "train_test_overlap_after_removal_punct_insensitive": overlap_wide,
        "provenance_train": {k: provenance[k] for k in PROVENANCE_VALUES if provenance[k]},
        "provenance_test": dict(collections.Counter(r["provenance"] for r in test)),
        "machine_translation_engines_train": dict(mt_engines),
        "equivalence": equivalence,
        "csv_rows": len(csv_rows),
        "rows_per_language": {
            lang: {"train": train_langs[lang], "test": len(test_by_lang.get(lang, []))}
            for lang in sorted(set(train_langs) | set(test_by_lang))
        },
        "skill_sources": dict(sorted(skills.items())),
        "excluded_repositories": dict(sorted(excluded.items())),
        "label_function": "ovos_localize/corpus/labels.py",
        "stats": dict(sorted(stats.items())),
    }
    manifest["files"] = {
        path.relative_to(corpus_dir).as_posix(): _sha256(path)
        for path in sorted(corpus_dir.glob("*/*.jsonl"))
    }
    (corpus_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    (corpus_dir / "README.md").write_text(render_card(manifest), encoding="utf-8")
    return manifest


def failures(manifest: dict) -> list:
    """The reasons the manifest's corpus must not be published."""
    out = []
    eq = manifest["equivalence"]
    if not eq["equal"]:
        out.append(
            f"the corpus and the CSV are not equivalent: {len(eq['only_in_corpus'])} pairs only in the "
            f"corpus, {len(eq['only_in_csv'])} only in the CSV, unaccounted CSV domains "
            f"{eq['csv_domains_unaccounted']}")
    for key in ("train_test_overlap_after_removal_exact", "train_test_overlap_after_removal_punct_insensitive"):
        if manifest[key]:
            out.append(f"{key} is {manifest[key]}, not 0")
    if not manifest["train_rows"] or not manifest["test_rows"]:
        out.append("a split is empty")
    return out


def render_card(manifest: dict) -> str:
    """The dataset card, every number read off *manifest*."""
    def share(counts: dict) -> str:
        total = sum(counts.values()) or 1
        return ", ".join(f"{k} {v:,} ({v / total:.1%})" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))

    engines = ", ".join(f"{k} {v:,}" for k, v in sorted(manifest["machine_translation_engines_train"].items()))
    per_lang = "\n".join(f"| {lang} | {c['train']:,} | {c['test']:,} |"
                         for lang, c in manifest["rows_per_language"].items())
    skills = "\n".join(f"| {sid} | {s['source_repo']} | `{s['source_ref']}` |"
                       for sid, s in manifest["skill_sources"].items())
    excluded = "\n".join(f"- `{repo}`: {why}" for repo, why in manifest["excluded_repositories"].items())
    supersedes = "\n".join(f"- [`OpenVoiceOS/{d}`](https://huggingface.co/datasets/OpenVoiceOS/{d})"
                           for d in SUPERSEDES)
    no_test = [lang for lang, c in manifest["rows_per_language"].items() if not c["test"]]
    eq = manifest["equivalence"]
    return f"""---
license: apache-2.0
task_categories:
  - text-classification
tags:
  - intent
  - ovos
  - openvoiceos
configs:
  - config_name: default
    data_files:
      - split: train
        path: "*/train.jsonl"
      - split: test
        path: "*/test.jsonl"
---

# OVOS intents

The intent corpus of the OpenVoiceOS skill fleet, exported daily by
[OpenVoiceOS/ovos-localize](https://github.com/OpenVoiceOS/ovos-localize) from the same skill data
that the localization site and the `ovos-localize-intents` CSV come from.

The train split is every `.intent` line of every skill, expanded: `<name>` from `name.voc` and
`{{name}}` from `name.entity` of the same language, a typed slot from that language's parser, and a
slot with no values left literal. The test split is the skills' end-to-end golden utterances at the
same commits. Labels are `<skill_id>:<intent_name>` (OVOS-INTENT-4 §3.2), where the skill id is the
one the entry point registers.

## Counts

| Count | Value |
| --- | --- |
| train rows | {manifest['train_rows']:,} |
| test rows | {manifest['test_rows']:,} |
| labels | {manifest['labels']:,} |
| skills | {manifest['skills']:,} |
| train languages | {manifest['languages_train']:,} |
| test languages | {manifest['languages_test']:,} |
| labels with no test row | {len(manifest['labels_without_test_rows']):,} |
| test labels with no train row | {len(manifest['test_labels_without_train_rows']):,} |
| train rows with a literal slot | {manifest['train_rows_with_a_literal_slot']:,} |

{len(no_test)} train languages have no test file. No empty test file is shipped.

## Provenance

Each row carries `provenance`. A train row takes it from the commit that last wrote its `.intent`
line: `native` for a line submitted through ovos-localize (`translate(<lang>): ...`),
`machine_translation` where the commit says a machine wrote it, with the engine in `mt_engine`
(`unrecorded` where the commit names none), and `unknown` for every other line. A row is never
`native` by default. A test row is `llm` where the golden file marks it `machine_generated`, else
`unknown`.

- train: {share(manifest['provenance_train'])}
- test: {share(manifest['provenance_test'])}
- machine translation engines (train rows): {engines or 'none'}

## Train and test do not overlap

{manifest['train_test_overlap_removed']:,} train rows matched a test utterance and were removed. After
the removal the overlap is {manifest['train_test_overlap_after_removal_exact']} under exact comparison and
{manifest['train_test_overlap_after_removal_punct_insensitive']} with edge punctuation stripped.

## Equivalence with the ovos-localize export

The `(skill_id, intent_name)` pairs of this corpus equal the pairs derived from the `.intent` rows
of `OpenVoiceOS/ovos-localize-intents` through the same label function: {eq['pairs_corpus']:,} pairs
on each side. The export fails, and nothing is published, when they differ.

## Layout

    {{lang}}/train.jsonl    train rows
    {{lang}}/test.jsonl     test rows
    manifest.json         the build record: counts, sources, exclusions, file hashes

Fields: `lang`, `label`, `skill_id`, `intent_name`, `utterance`, `template` (train only),
`source_repo`, `source_ref`, `source_file`, `provenance`, `mt_engine`.

## Rows per language

| Language | Train | Test |
| --- | --- | --- |
{per_lang}

## Sources

| Skill id | Repository | Commit |
| --- | --- | --- |
{skills}

Repositories in ovos-localize that are not in this corpus:

{excluded}

## Supersedes

These datasets are retired and stay available for reproducibility:

{supersedes}

## Credit

Funded by the [NGI0 Commons Fund](https://nlnet.nl/project/OpenVoiceOS) /
[NLnet](https://nlnet.nl) under grant agreement No
[101135429](https://cordis.europa.eu/project/id/101135429), through the European Commission's
[Next Generation Internet](https://ngi.eu) programme.
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skills", default="data/skills", help="the data/skills directory")
    parser.add_argument("--out", required=True, help="directory for the CSV and the ovos-intents tree")
    args = parser.parse_args(argv)
    manifest = export(Path(args.skills), Path(args.out))
    print(json.dumps({k: v for k, v in manifest.items() if not isinstance(v, (list, dict))}, indent=1))
    problems = failures(manifest)
    for problem in problems:
        print(f"[gate] {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
