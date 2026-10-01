"""CLI entry point that removes the submission branches that are finished.

The submit workflow cannot delete its own branch: it opens the pull request
and ends, and the merge happens later, in the target repository, under a
maintainer's hand. This command is the other half. It reads the pull
request each ``translate/`` branch opened and deletes the ref when that
pull request is merged or closed. A branch whose pull request is still open
is left alone, and so is a branch that never got one.

It is a dry run unless ``--apply`` is given. The output names every branch,
the pull request the verdict rests on, and ends with the counts: how many
branches were found, how many are finished, and how many were deleted.

The GitHub API is reached through ``gh``, which the workflow runs with the
App installation token for the owner being swept.

Exit codes:

0
    The sweep ran. Branches may have been deleted, or none needed to be.
1
    A repository could not be read, or a delete was refused. The sweep
    finishes the other repositories first and reports what failed.
2
    Bad arguments.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from itertools import chain
from urllib.parse import urlencode

from ovos_localize.sync.stale_branches import DELETE, format_reports, sweep_repo


def gh_api(path: str, params: Mapping | None = None, paginate: bool = False, method: str = "GET"):
    """Call the GitHub API through ``gh`` and return the parsed response.

    Raises:
        LookupError: The resource does not exist, which for a branch or a
            path is an answer and not a failure.
        RuntimeError: Anything else ``gh`` refused, including a protected
            ref that may not be deleted.
    """
    # The path carries branch names, which contain slashes by design. Only
    # the query string is encoded; the path segments are already literal.
    url = path
    if params:
        url = f"{path}?{urlencode(params)}"
    command = ["gh", "api", "--method", method, url]
    if paginate:
        # --slurp returns one array per page inside an outer array, which is
        # parseable. Plain --paginate concatenates the pages as "][", and
        # splicing that back together corrupts any string containing it.
        command += ["--paginate", "--slurp"]
    if method == "DELETE":
        command.append("--silent")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        # "HTTP 404" is the status gh reports. A bare "404" also matches a
        # refusal whose body happens to carry those digits, such as a
        # validation error quoting a ref named error404, and a refusal read as
        # a missing resource is a delete that reports nothing wrong.
        if "HTTP 404" in message or "Not Found" in message:
            raise LookupError(f"{method} {url}: not found")
        raise RuntimeError(f"{method} {url}: {message}")
    body = result.stdout.strip()
    if not body:
        return {}
    parsed = json.loads(body)
    if paginate:
        return list(chain.from_iterable(parsed))
    return parsed


def main(argv: Sequence[str] | None = None, api=gh_api) -> int:
    """Sweep the submission branches of every named repository."""
    parser = argparse.ArgumentParser(
        description="Delete the translate/ branches whose pull request is merged or closed.",
    )
    parser.add_argument("--owner", required=True, help="the organization the repositories belong to")
    parser.add_argument(
        "repos", nargs="+",
        help="repository names to sweep, without the owner",
    )
    parser.add_argument(
        "--base", default="",
        help="branch to compare content against; the repository's default branch when omitted",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="delete the refs. Without it the command only reports what it would delete.",
    )
    parser.add_argument(
        "--no-compare-content", action="store_true",
        help="skip reading each branch's paths on the base branch",
    )
    args = parser.parse_args(argv)

    reports = []
    failures: list[str] = []
    for repo in args.repos:
        try:
            reports.extend(sweep_repo(
                args.owner, repo, api,
                base=args.base,
                apply=args.apply,
                compare_content=not args.no_compare_content,
            ))
        except (RuntimeError, LookupError, KeyError) as error:
            failures.append(f"{args.owner}/{repo}: {error}")

    print(f"swept {len(args.repos)} repositories for branches under translate/")
    print(format_reports(reports, apply=args.apply))
    for failure in failures:
        print(f"[ERROR] could not sweep {failure}")

    refused = [r for r in reports if r.error]
    for report in refused:
        print(f"[ERROR] could not delete {report.repo} {report.branch}: {report.error}")

    if not args.apply and any(r.action == DELETE for r in reports):
        print("Re-run with --apply to delete them.")
    return 1 if failures or refused else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
