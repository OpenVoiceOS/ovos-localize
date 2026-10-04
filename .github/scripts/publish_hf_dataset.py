#!/usr/bin/env python3
"""Publish the flat intent CSV to the ovos-localize-intents HF dataset.

The dataset holds intent training data only: one row per expanded template
of a skill's ``.intent`` file (OVOS-INTENT-2 §4.1). ``ovos_localize_intents.csv``
is regenerated from ``data/datasets/classification/*.jsonl`` and keeps a row
only when its source file has the ``.intent`` extension; the ``.voc`` rows of
the classification corpus stay out.

The other corpora under ``data/datasets/`` (``.voc``, ``.dialog`` and other
resource kinds) are served from the ovos-localize site and are not part of
this dataset. Any ``data/datasets/`` tree left in the dataset repo is deleted
in the same commit that uploads the CSV, so each run replaces the dataset in
full.

The dataset repo's README is left untouched: this repo carries no HF
dataset-card template to regenerate it from.
"""
import csv
import json
import os
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

REPO_ID = "OpenVoiceOS/ovos-localize-intents"
CLASSIFICATION_DIR = Path("data/datasets/classification")
CSV_PATH_IN_REPO = "ovos_localize_intents.csv"
CSV_COLUMNS = ("lang", "domain", "intent", "sentence")
STALE_PREFIX_IN_REPO = "data/datasets/"
INTENT_SUFFIX = ".intent"


def build_flat_csv(out_path: Path) -> int:
    """Write the flat lang/domain/intent/sentence CSV and return the row count."""
    rows = []
    for jsonl_file in sorted(CLASSIFICATION_DIR.glob("*.jsonl")):
        with jsonl_file.open(encoding="utf-8") as f:
            for line in f:
                sample = json.loads(line)
                if not sample["intent"].endswith(INTENT_SUFFIX):
                    continue
                rows.append(
                    (sample["lang"], sample["skill"], sample["intent"], sample["text"])
                )
    rows.sort()

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        print("HF_TOKEN is not set; refusing to publish.")
        return

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "OpenVoiceOS/ovos-localize")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    commit_message = f"chore: refresh intent dataset from {repository} run {run_id}"

    csv_out = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / CSV_PATH_IN_REPO
    row_count = build_flat_csv(csv_out)
    print(f"generated {csv_out} with {row_count} rows")

    api = HfApi(token=token)
    operations = [
        CommitOperationAdd(path_in_repo=CSV_PATH_IN_REPO, path_or_fileobj=str(csv_out))
    ]
    remote_files = api.list_repo_files(repo_id=REPO_ID, repo_type="dataset")
    if any(name.startswith(STALE_PREFIX_IN_REPO) for name in remote_files):
        operations.append(
            CommitOperationDelete(path_in_repo=STALE_PREFIX_IN_REPO, is_folder=True)
        )

    api.create_commit(
        repo_id=REPO_ID,
        repo_type="dataset",
        operations=operations,
        commit_message=commit_message,
        commit_description=run_url,
    )
    print(f"published {csv_out} to {REPO_ID}:{CSV_PATH_IN_REPO}")
    if len(operations) > 1:
        print(f"deleted {REPO_ID}:{STALE_PREFIX_IN_REPO}")


if __name__ == "__main__":
    main()
