#!/usr/bin/env python3
"""Publish the intent CSV and the intents corpus to Hugging Face.

Both come from one export of ovos-localize's skill data
(``ovos-localize-export-intents``), which reads every skill file once and
fails when the corpus and the CSV are not equivalent. This script uploads
what that export wrote and nothing else:

* ``ovos_localize_intents.csv`` to ``OpenVoiceOS/ovos-localize-intents``: one
  row per expanded template of a skill's ``.intent`` file (OVOS-INTENT-2
  §4.1). Any ``data/datasets/`` tree left in that repo is deleted in the same
  commit, so the dataset holds intent training data only.
* the ``ovos-intents`` tree to ``OpenVoiceOS/ovos-intents``: ``{lang}/train.jsonl``,
  ``{lang}/test.jsonl``, ``manifest.json`` and the card generated from it.
  Every other file in that repo except ``.gitattributes`` is deleted in the
  same commit, so each run replaces the split files in full.

The ovos-localize-intents README is left untouched: this repo carries no card
template for it.

Each repo is published on its own: a failure on one is printed and does not
stop the other, and the script exits non-zero when any repo failed. The corpus
goes first because it is the one a model trains on. A repo missing on the Hub
is reported, never created.

An export that holds no CSV row or no corpus row is refused before the Hub is
contacted: replacing a dataset in full from an empty tree would delete it.
"""
import os
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

CSV_REPO_ID = "OpenVoiceOS/ovos-localize-intents"
CSV_PATH_IN_REPO = "ovos_localize_intents.csv"
STALE_PREFIX_IN_REPO = "data/datasets/"
CORPUS_REPO_ID = "OpenVoiceOS/ovos-intents"
CORPUS_DIR = "ovos-intents"
KEEP_IN_CORPUS_REPO = {".gitattributes"}


def csv_operations(export_dir: Path, remote_files: list) -> list:
    """Upload the CSV and delete any ``data/datasets/`` tree in the same commit."""
    operations = [CommitOperationAdd(path_in_repo=CSV_PATH_IN_REPO,
                                     path_or_fileobj=str(export_dir / CSV_PATH_IN_REPO))]
    if any(name.startswith(STALE_PREFIX_IN_REPO) for name in remote_files):
        operations.append(CommitOperationDelete(path_in_repo=STALE_PREFIX_IN_REPO, is_folder=True))
    return operations


def export_rows(export_dir: Path) -> tuple:
    """``(csv_rows, corpus_rows)``: data rows of the CSV and of the corpus split files."""
    csv_path = export_dir / CSV_PATH_IN_REPO
    csv_rows = 0
    if csv_path.is_file():
        with csv_path.open(encoding="utf-8") as fh:
            csv_rows = max(sum(1 for line in fh if line.strip()) - 1, 0)
    corpus_rows = 0
    for path in (export_dir / CORPUS_DIR).glob("*/*.jsonl"):
        with path.open(encoding="utf-8") as fh:
            corpus_rows += sum(1 for line in fh if line.strip())
    return csv_rows, corpus_rows


def corpus_operations(export_dir: Path, remote_files: list) -> list:
    """Upload the corpus tree and delete every remote file it does not hold."""
    corpus_dir = export_dir / CORPUS_DIR
    local = sorted(p.relative_to(corpus_dir).as_posix() for p in corpus_dir.rglob("*") if p.is_file())
    operations = [CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(corpus_dir / name))
                  for name in local]
    operations += [CommitOperationDelete(path_in_repo=name)
                   for name in sorted(set(remote_files) - set(local) - KEEP_IN_CORPUS_REPO)]
    return operations


def main() -> None:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print("HF_TOKEN is not set; refusing to publish.")
        return

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "OpenVoiceOS/ovos-localize")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    export_dir = Path(os.environ.get("INTENTS_EXPORT_DIR")
                      or Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "intents-export")

    csv_rows, corpus_rows = export_rows(export_dir)
    if not csv_rows or not corpus_rows:
        sys.exit(f"{export_dir} holds {csv_rows} CSV rows and {corpus_rows} corpus rows; "
                 "refusing to publish an empty export, which would delete the published datasets.")

    api = HfApi(token=token)
    failed = []
    for repo_id, build in ((CORPUS_REPO_ID, corpus_operations), (CSV_REPO_ID, csv_operations)):
        try:
            operations = build(export_dir, api.list_repo_files(repo_id=repo_id, repo_type="dataset"))
            api.create_commit(
                repo_id=repo_id,
                repo_type="dataset",
                operations=operations,
                commit_message=f"chore: refresh from {repository} run {run_id}",
                commit_description=run_url,
            )
        except Exception as exc:
            print(f"FAILED {repo_id}: {type(exc).__name__}: {exc}")
            failed.append(repo_id)
            continue
        added = sum(isinstance(op, CommitOperationAdd) for op in operations)
        print(f"published {repo_id}: {added} files added, {len(operations) - added} deleted")
    if failed:
        sys.exit(f"failed to publish: {', '.join(failed)}")


if __name__ == "__main__":
    main()
