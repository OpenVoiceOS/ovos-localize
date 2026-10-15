#!/usr/bin/env python3
"""Publish the daily intents build to the ``localize-daily`` branch of ``OpenVoiceOS/ovos-intents``.

The build comes from one export of ovos-localize's skill data
(``ovos-localize-export-intents``): ``{lang}/train.jsonl``, ``{lang}/test.jsonl``,
``manifest.json`` and the card generated from it.

The published ``ovos-intents`` corpus on ``main`` is built by ovos-m2v-pipeline,
with its own layout and labels, so this script never writes ``main`` and never
touches a tag. It writes one branch, ``localize-daily``, and it only adds or
replaces files there: it never deletes one, because the dataset is add-only.
The branch is created on the first run from the repository's first commit, so
it holds the localize build and not a copy of the corpus on ``main``.

An export that holds no row is refused before the Hub is contacted. A missing
``HF_TOKEN`` and every Hub error exit non-zero, so the run that called this
turns red.
"""
import os
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

CSV_PATH_IN_REPO = "ovos_localize_intents.csv"
CORPUS_REPO_ID = "OpenVoiceOS/ovos-intents"
CORPUS_DIR = "ovos-intents"
BRANCH = "localize-daily"


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


def corpus_operations(export_dir: Path) -> list:
    """Upload every file of the corpus tree. Nothing is ever deleted."""
    corpus_dir = export_dir / CORPUS_DIR
    local = sorted(p.relative_to(corpus_dir).as_posix() for p in corpus_dir.rglob("*") if p.is_file())
    return [CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(corpus_dir / name)) for name in local]


def publish(api: HfApi, export_dir: Path, message: str, description: str) -> int:
    """Create the branch if it is missing, then commit the build to it.

    Returns:
        The number of files added or replaced.
    """
    first_commit = api.list_repo_commits(repo_id=CORPUS_REPO_ID, repo_type="dataset")[-1].commit_id
    api.create_branch(repo_id=CORPUS_REPO_ID, repo_type="dataset", branch=BRANCH,
                      revision=first_commit, exist_ok=True)
    operations = corpus_operations(export_dir)
    api.create_commit(
        repo_id=CORPUS_REPO_ID,
        repo_type="dataset",
        revision=BRANCH,
        operations=operations,
        commit_message=message,
        commit_description=description,
    )
    return len(operations)


def main() -> None:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        sys.exit("HF_TOKEN is not set; refusing to publish.")

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "OpenVoiceOS/ovos-localize")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    export_dir = Path(os.environ.get("INTENTS_EXPORT_DIR")
                      or Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "intents-export")

    csv_rows, corpus_rows = export_rows(export_dir)
    if not csv_rows or not corpus_rows:
        sys.exit(f"{export_dir} holds {csv_rows} CSV rows and {corpus_rows} corpus rows; "
                 "refusing to publish an empty export.")

    try:
        added = publish(HfApi(token=token), export_dir,
                        f"chore: refresh from {repository} run {run_id}", run_url)
    except Exception as error:
        sys.exit(f"FAILED {CORPUS_REPO_ID}@{BRANCH}: {type(error).__name__}: {error}")
    print(f"published {CORPUS_REPO_ID}@{BRANCH}: {added} files added or replaced, none deleted")


if __name__ == "__main__":
    main()
