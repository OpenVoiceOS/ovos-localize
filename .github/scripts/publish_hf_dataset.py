#!/usr/bin/env python3
"""Push data/datasets/ and the flat CSV export to the ovos-localize-intents HF dataset.

Two things are published in one commit:

* ``data/datasets/`` is mirrored into the ``data/datasets/`` path of the
  dataset repo, pruning only that same prefix.
* ``ovos_localize_intents.csv`` at the repo root is regenerated from
  ``data/datasets/classification/*.jsonl`` (the ``intent`` samples only,
  matching what the CSV has always contained: no ``.voc`` rows) so the
  flat export and the datasets-server statistics stay in sync with the
  corpus instead of freezing at whatever the CSV last held.

The dataset repo's README is left untouched: this repo carries no HF
dataset-card template to regenerate it from.
"""
import csv
import json
import os
from pathlib import Path

from huggingface_hub import HfApi

REPO_ID = "OpenVoiceOS/ovos-localize-intents"
LOCAL_DIR = "data/datasets"
PATH_IN_REPO = "data/datasets"
CLASSIFICATION_DIR = Path(LOCAL_DIR) / "classification"
CSV_PATH_IN_REPO = "ovos_localize_intents.csv"
CSV_COLUMNS = ("lang", "domain", "intent", "sentence")


def build_flat_csv(out_path: Path) -> int:
    """Write the flat lang/domain/intent/sentence CSV and return the row count."""
    rows = []
    for jsonl_file in sorted(CLASSIFICATION_DIR.glob("*.jsonl")):
        with jsonl_file.open(encoding="utf-8") as f:
            for line in f:
                sample = json.loads(line)
                if sample.get("file_type") != "intent":
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
    commit_message = f"chore: refresh training corpora from {repository} run {run_id}"

    csv_out = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / CSV_PATH_IN_REPO
    row_count = build_flat_csv(csv_out)
    print(f"generated {csv_out} with {row_count} rows")

    api = HfApi(token=token)
    api.upload_folder(
        repo_id=REPO_ID,
        repo_type="dataset",
        folder_path=LOCAL_DIR,
        path_in_repo=PATH_IN_REPO,
        # huggingface_hub strips path_in_repo from each remote filename before
        # matching delete_patterns (HfApi._prepare_folder_deletions), so the
        # pattern must be relative to path_in_repo, not repo-root-relative.
        # Root files (README.md, the CSV, .gitattributes) are never candidates
        # regardless of this pattern: the same helper only considers files
        # whose repo-root path starts with path_in_repo.
        delete_patterns=["**"],
        commit_message=commit_message,
        commit_description=run_url,
    )
    print(f"published {LOCAL_DIR} to {REPO_ID}:{PATH_IN_REPO}")

    api.upload_file(
        repo_id=REPO_ID,
        repo_type="dataset",
        path_or_fileobj=str(csv_out),
        path_in_repo=CSV_PATH_IN_REPO,
        commit_message=commit_message,
        commit_description=run_url,
    )
    print(f"published {csv_out} to {REPO_ID}:{CSV_PATH_IN_REPO}")


if __name__ == "__main__":
    main()
