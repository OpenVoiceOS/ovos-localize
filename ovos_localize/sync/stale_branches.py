"""Decide whether a submission branch still has a reason to exist.

The submit pipeline opens one branch per translated file, named
``translate/<lang>/<file_key>-<timestamp>``, and opens a pull request from
it. The pipeline's run ends there: the pull request is merged by a
maintainer of the target repository, in that repository, so the run that
created the branch is long gone by the time the branch becomes garbage.
Nothing deleted it, and the refs accumulated until a reader listing the
branches of a skill repository could no longer tell which submissions were
still open.

The authority on a branch is the state of the pull request opened from it.
A merged pull request put the file on the base branch, and a closed one
decided against it; either way the branch has delivered its verdict. Only
an open pull request still needs its head.

Content identity is reported and never decides. A squash merge leaves the
branch tip outside the base branch's history, and any later edit to the
same file makes a merged branch's content differ from the base branch, so
"the file still matches" is neither necessary nor sufficient for a branch
to be finished.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import quote

SUBMISSION_PREFIX = "translate/"

KEEP = "keep"
DELETE = "delete"

# Reasons, in the order classify_pulls considers them.
OPEN_PULL = "open-pull-request"
MERGED = "merged"
CLOSED_UNMERGED = "closed-unmerged"
NO_PULL = "no-pull-request"

_REASON_TEXT = {
    OPEN_PULL: "pull request {numbers} is open",
    MERGED: "pull request {numbers} merged",
    CLOSED_UNMERGED: "pull request {numbers} closed without merging",
    NO_PULL: "no pull request was ever opened from this branch",
}


def is_submission_branch(name: str) -> bool:
    """Tell whether ``name`` is a branch the submit pipeline created."""
    return name.startswith(SUBMISSION_PREFIX) and len(name) > len(SUBMISSION_PREFIX)


@dataclass
class BranchReport:
    """What the sweep found out about one branch, and what it did.

    Attributes:
        repo: The ``owner/repo`` the branch lives in.
        branch: The branch name.
        action: ``KEEP`` or ``DELETE``.
        reason: One of the reason constants in this module.
        pulls: Numbers of the pull requests opened from this branch.
        paths_on_base: True when every path the branch touches holds the
            same bytes on the base branch, False when at least one differs,
            and None when the comparison was not made.
        deleted: True once the ref is gone. False in a dry run, and false
            when the delete was refused.
        error: Why the delete did not happen, when it was attempted and
            refused.
    """

    repo: str
    branch: str
    action: str
    reason: str
    pulls: list[int] = field(default_factory=list)
    paths_on_base: bool | None = None
    deleted: bool = False
    error: str = ""

    @property
    def explanation(self) -> str:
        """The reason as a sentence, naming the pull requests it rests on."""
        numbers = ", ".join(f"#{n}" for n in self.pulls) or "none"
        return _REASON_TEXT[self.reason].format(numbers=numbers)


def classify_pulls(pulls: Sequence[Mapping]) -> tuple[str, str]:
    """Decide a branch's fate from the pull requests opened from it.

    A branch can carry more than one pull request: a submission that was
    closed and reopened, or re-dispatched, leaves several against the same
    head. One of them being open is enough to keep the branch, whatever the
    others say.

    A branch with no pull request at all is kept. The pipeline pushes the
    branch before it opens the pull request, so a branch without one is a
    run that failed in between, and its commit is the only copy of that
    translation inside the repository.

    Args:
        pulls: Pull request objects as the GitHub API returns them. Only
            ``state`` and ``merged_at`` are read.

    Returns:
        The action to take and the reason for it.
    """
    if not pulls:
        return KEEP, NO_PULL
    if any(pull.get("state") == "open" for pull in pulls):
        return KEEP, OPEN_PULL
    if any(pull.get("merged_at") for pull in pulls):
        return DELETE, MERGED
    return DELETE, CLOSED_UNMERGED


def _pull_numbers(pulls: Iterable[Mapping]) -> list[int]:
    return sorted(pull["number"] for pull in pulls if "number" in pull)


def pulls_for_branch(owner: str, repo: str, branch: str, api: Callable) -> list[Mapping]:
    """Return every pull request whose head is ``branch``.

    The query is by head ref. The commit-based association
    (``/commits/{ref}/pulls``) misses pull requests this one finds: on
    ovos-skill-date-time it reported no pull request for two branches that
    carry #394 and #396, so a sweep built on it would read a closed
    submission as a branch that never got one.
    """
    head = f"{owner}:{branch}"
    return list(api(f"repos/{owner}/{repo}/pulls", params={"state": "all", "head": head}, paginate=True))


def paths_match_base(owner: str, repo: str, branch: str, base: str, api: Callable) -> bool | None:
    """Tell whether the branch's own paths hold the same bytes on ``base``.

    The three-dot comparison names the paths the branch changed since it
    forked. Each of those paths is then read on both refs and the blob ids
    are compared, which answers the question the branch's age cannot
    disturb: a branch that forked months ago differs from the base branch
    in many files it never touched.

    Returns None when the comparison cannot be made.
    """
    try:
        comparison = api(f"repos/{owner}/{repo}/compare/{quote(base, safe='')}...{quote(branch, safe='')}")
    except LookupError:
        return None
    files = comparison.get("files")
    if files is None:
        # The comparison omits the file list on a diff it considers too
        # large. An absent list is not an empty one: the question is
        # unanswered unless the branch carries no commit of its own.
        return True if comparison.get("ahead_by") == 0 else None
    changed = [entry["filename"] for entry in files]
    if not changed:
        # The branch changed nothing since the fork point, so there is
        # nothing of its own that could be missing from the base branch.
        return True
    for path in changed:
        branch_blob = _blob_id(owner, repo, path, branch, api)
        base_blob = _blob_id(owner, repo, path, base, api)
        if branch_blob is None or base_blob is None or branch_blob != base_blob:
            return False
    return True


def _blob_id(owner: str, repo: str, path: str, ref: str, api: Callable) -> str | None:
    try:
        entry = api(f"repos/{owner}/{repo}/contents/{quote(path)}", params={"ref": ref})
    except LookupError:
        return None
    if isinstance(entry, list):
        # A directory at that path on this ref; not a file to compare.
        return None
    return entry.get("sha")


def sweep_repo(
    owner: str,
    repo: str,
    api: Callable,
    *,
    base: str = "",
    apply: bool = False,
    compare_content: bool = True,
) -> list[BranchReport]:
    """Classify every submission branch of one repository, and delete the finished ones.

    Args:
        owner: The repository owner.
        repo: The repository name.
        api: Reads the GitHub API. Called as
            ``api(path, params=..., paginate=...)`` for a read and
            ``api(path, method="DELETE")`` for the delete. It raises
            ``LookupError`` for a missing resource and ``RuntimeError`` for
            a refused one.
        base: The branch to compare content against. The repository's
            default branch when empty.
        apply: Delete the refs. A dry run when false.
        compare_content: Read each branch's paths on the base branch.

    Returns:
        One report per submission branch, in branch-name order. A
        repository with no submission branch returns an empty list and
        makes no further call.
    """
    branches = [
        entry["name"]
        for entry in api(f"repos/{owner}/{repo}/branches", paginate=True)
        if is_submission_branch(entry["name"])
    ]
    if not branches:
        return []

    if not base:
        base = api(f"repos/{owner}/{repo}")["default_branch"]

    reports: list[BranchReport] = []
    for branch in sorted(branches):
        pulls = pulls_for_branch(owner, repo, branch, api)
        action, reason = classify_pulls(pulls)
        report = BranchReport(
            repo=f"{owner}/{repo}",
            branch=branch,
            action=action,
            reason=reason,
            pulls=_pull_numbers(pulls),
        )
        if compare_content:
            report.paths_on_base = paths_match_base(owner, repo, branch, base, api)
        if action == DELETE and apply:
            try:
                api(f"repos/{owner}/{repo}/git/refs/heads/{quote(branch, safe='')}", method="DELETE")
                report.deleted = True
            except (RuntimeError, LookupError) as error:
                report.error = str(error)
        reports.append(report)
    return reports


def format_reports(reports: Sequence[BranchReport], *, apply: bool) -> str:
    """Render the sweep as the text a person reads in the run log."""
    lines: list[str] = []
    for report in sorted(reports, key=lambda r: (r.repo, r.branch)):
        if report.paths_on_base is None:
            content = "content not compared"
        elif report.paths_on_base:
            content = "its paths match the base branch"
        else:
            content = "its paths differ from the base branch"
        if report.action == KEEP:
            state = "KEEP   "
        elif report.deleted:
            state = "DELETED"
        elif report.error:
            state = "REFUSED"
        else:
            state = "STALE  "
        line = f"{state} {report.repo} {report.branch} -- {report.explanation}; {content}"
        if report.error:
            line += f"; {report.error}"
        lines.append(line)

    found = len(reports)
    stale = sum(1 for r in reports if r.action == DELETE)
    deleted = sum(1 for r in reports if r.deleted)
    refused = sum(1 for r in reports if r.error)
    kept = found - stale
    lines.append("")
    lines.append(f"{found} submission branches found, {stale} finished, {kept} still needed.")
    if apply:
        lines.append(f"{deleted} deleted, {refused} refused.")
    else:
        lines.append(f"0 deleted: this was a dry run. {stale} would be deleted.")
    return "\n".join(lines)
