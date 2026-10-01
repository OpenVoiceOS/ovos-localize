"""Tests for the submission-branch sweep.

The pull request states here are the ones measured on the three skill
repositories that carried stale branches: ovos-skill-alerts, whose branches
all carry a merged pull request, ovos-skill-date-time, which carries two
closed unmerged ones and one branch that never got a pull request at all,
and ovos-skill-spelling, whose branch names a path its base branch no
longer has.
"""

import json
import unittest

from ovos_localize.sync.stale_branches import (
    CLOSED_UNMERGED,
    DELETE,
    KEEP,
    MERGED,
    NO_PULL,
    OPEN_PULL,
    BranchReport,
    classify_pulls,
    format_reports,
    is_submission_branch,
    paths_match_base,
    pulls_for_branch,
    sweep_repo,
)


def merged(number, at="2026-08-26T12:54:40Z"):
    return {"number": number, "state": "closed", "merged_at": at}


def closed(number):
    return {"number": number, "state": "closed", "merged_at": None}


def opened(number):
    return {"number": number, "state": "open", "merged_at": None}


class FakeApi:
    """A GitHub API that answers from a dict and records what it was asked.

    Any path not given raises LookupError, which is what the real client
    raises for a 404. That makes an unexpected call visible as a failure
    rather than as a silently empty answer.
    """

    def __init__(self, routes, deletes_refused=()):
        self.routes = routes
        self.deletes_refused = set(deletes_refused)
        self.calls = []
        self.deleted = []

    def __call__(self, path, params=None, paginate=False, method="GET"):
        key = path
        if params:
            key = f"{path}?{json.dumps(params, sort_keys=True)}"
        self.calls.append((method, key))
        if method == "DELETE":
            if path in self.deletes_refused:
                raise RuntimeError("protected ref")
            self.deleted.append(path)
            return {}
        if key not in self.routes:
            raise LookupError(f"not found: {key}")
        return self.routes[key]


def branch_routes(owner, repo, branches, default_branch="dev"):
    return {
        f"repos/{owner}/{repo}/branches": [{"name": name} for name in branches],
        f"repos/{owner}/{repo}": {"default_branch": default_branch},
    }


def pulls_key(owner, repo, branch):
    params = {"state": "all", "head": f"{owner}:{branch}"}
    return f"repos/{owner}/{repo}/pulls?{json.dumps(params, sort_keys=True)}"


class TestIsSubmissionBranch(unittest.TestCase):
    def test_pipeline_branch_names_are_recognised(self):
        for name in (
            "translate/kab/all_day.voc-1787734123",
            "translate/nl-NL/abbreviation_friday.dialog-1774032096",
            "translate/kab-DZ/date.dialog-1786988119",
        ):
            self.assertTrue(is_submission_branch(name), name)

    def test_other_branches_are_not_touched(self):
        for name in ("dev", "main", "master", "fix/json-resource-submission",
                     "i18n/enable-br-FR-1790474864", "translate/", "release/1.2.3"):
            self.assertFalse(is_submission_branch(name), name)


class TestClassifyPulls(unittest.TestCase):
    def test_merged_pull_request_finishes_the_branch(self):
        self.assertEqual((DELETE, MERGED), classify_pulls([merged(161)]))

    def test_closed_unmerged_pull_request_finishes_the_branch(self):
        self.assertEqual((DELETE, CLOSED_UNMERGED), classify_pulls([closed(396)]))

    def test_open_pull_request_keeps_the_branch(self):
        self.assertEqual((KEEP, OPEN_PULL), classify_pulls([opened(500)]))

    def test_branch_without_a_pull_request_is_kept(self):
        self.assertEqual((KEEP, NO_PULL), classify_pulls([]))

    def test_one_open_pull_request_outvotes_a_merged_one(self):
        # A resubmitted file can carry several pull requests against the same
        # head. Deleting the ref would close the open one.
        self.assertEqual((KEEP, OPEN_PULL), classify_pulls([merged(161), opened(500)]))

    def test_one_open_pull_request_outvotes_a_closed_one(self):
        self.assertEqual((KEEP, OPEN_PULL), classify_pulls([closed(396), opened(500)]))

    def test_merged_is_reported_ahead_of_closed(self):
        self.assertEqual((DELETE, MERGED), classify_pulls([closed(396), merged(161)]))

    def test_empty_merged_at_is_not_a_merge(self):
        self.assertEqual((DELETE, CLOSED_UNMERGED),
                         classify_pulls([{"number": 1, "state": "closed", "merged_at": ""}]))


class TestPullsForBranch(unittest.TestCase):
    def test_the_query_is_by_head_ref(self):
        branch = "translate/de-DE/current_date.intent-1790459264"
        api = FakeApi({pulls_key("OpenVoiceOS", "ovos-skill-date-time", branch): [closed(396)]})
        found = pulls_for_branch("OpenVoiceOS", "ovos-skill-date-time", branch, api)
        self.assertEqual([396], [p["number"] for p in found])
        self.assertEqual(
            [("GET", pulls_key("OpenVoiceOS", "ovos-skill-date-time", branch))],
            api.calls,
        )

    def test_a_branch_with_no_pull_request_reads_as_an_empty_list(self):
        api = FakeApi({pulls_key("o", "r", "translate/kab/x.voc-1"): []})
        self.assertEqual([], pulls_for_branch("o", "r", "translate/kab/x.voc-1", api))


class TestPathsMatchBase(unittest.TestCase):
    def test_identical_blob_reads_as_on_the_base_branch(self):
        api = FakeApi({
            "repos/o/r/compare/dev...translate/kab/all_day.voc-1":
                {"files": [{"filename": "locale/kab/vocab/all_day.voc"}]},
            'repos/o/r/contents/locale/kab/vocab/all_day.voc?{"ref": "translate/kab/all_day.voc-1"}':
                {"sha": "abc123"},
            'repos/o/r/contents/locale/kab/vocab/all_day.voc?{"ref": "dev"}':
                {"sha": "abc123"},
        })
        self.assertIs(True, paths_match_base("o", "r", "translate/kab/all_day.voc-1", "dev", api))

    def test_a_different_blob_reads_as_not_on_the_base_branch(self):
        api = FakeApi({
            "repos/o/r/compare/dev...translate/kab/at_time.dialog-1":
                {"files": [{"filename": "locale/kab/dialog/at_time.dialog"}]},
            'repos/o/r/contents/locale/kab/dialog/at_time.dialog?{"ref": "translate/kab/at_time.dialog-1"}':
                {"sha": "abc123"},
            'repos/o/r/contents/locale/kab/dialog/at_time.dialog?{"ref": "dev"}':
                {"sha": "def456"},
        })
        self.assertIs(False, paths_match_base("o", "r", "translate/kab/at_time.dialog-1", "dev", api))

    def test_a_path_the_base_branch_no_longer_has_reads_as_not_matching(self):
        # ovos-skill-spelling#80 moved word.entity into spell.intent, so the
        # path the branch names is gone from the base branch.
        branch = "translate/kab/word.entity-1788262107"
        api = FakeApi({
            f"repos/o/r/compare/dev...{branch}":
                {"files": [{"filename": "locale/kab/word.entity"}]},
            f'repos/o/r/contents/locale/kab/word.entity?{{"ref": "{branch}"}}': {"sha": "abc123"},
        })
        self.assertIs(False, paths_match_base("o", "r", branch, "dev", api))

    def test_a_branch_that_changed_nothing_matches(self):
        api = FakeApi({"repos/o/r/compare/dev...translate/kab/x.voc-1": {"files": []}})
        self.assertIs(True, paths_match_base("o", "r", "translate/kab/x.voc-1", "dev", api))

    def test_an_omitted_file_list_on_a_branch_with_a_commit_reads_as_unknown(self):
        # The comparison drops "files" on a diff it considers too large. Read
        # as an empty list, that answers "the paths match" without looking.
        api = FakeApi({"repos/o/r/compare/dev...translate/kab/x.voc-1": {"ahead_by": 1}})
        self.assertIsNone(paths_match_base("o", "r", "translate/kab/x.voc-1", "dev", api))

    def test_an_omitted_file_list_on_a_branch_with_no_commit_reads_as_matching(self):
        api = FakeApi({"repos/o/r/compare/dev...translate/kab/x.voc-1": {"ahead_by": 0}})
        self.assertIs(True, paths_match_base("o", "r", "translate/kab/x.voc-1", "dev", api))

    def test_an_unreadable_comparison_reads_as_unknown(self):
        self.assertIsNone(paths_match_base("o", "r", "translate/kab/x.voc-1", "dev", FakeApi({})))

    def test_a_directory_at_the_path_reads_as_not_matching(self):
        api = FakeApi({
            "repos/o/r/compare/dev...translate/kab/x.voc-1": {"files": [{"filename": "locale/kab"}]},
            'repos/o/r/contents/locale/kab?{"ref": "translate/kab/x.voc-1"}': [{"name": "a.voc"}],
            'repos/o/r/contents/locale/kab?{"ref": "dev"}': [{"name": "a.voc"}],
        })
        self.assertIs(False, paths_match_base("o", "r", "translate/kab/x.voc-1", "dev", api))


class TestSweepRepo(unittest.TestCase):
    def test_a_repository_with_no_submission_branch_makes_one_call(self):
        api = FakeApi(branch_routes("o", "r", ["dev", "fix/something"]))
        self.assertEqual([], sweep_repo("o", "r", api, compare_content=False))
        self.assertEqual([("GET", "repos/o/r/branches")], api.calls)

    def test_a_dry_run_deletes_nothing_and_still_classifies(self):
        branch = "translate/kab/all_day.voc-1787734123"
        routes = branch_routes("OpenVoiceOS", "ovos-skill-alerts", ["dev", branch])
        routes[pulls_key("OpenVoiceOS", "ovos-skill-alerts", branch)] = [merged(161)]
        api = FakeApi(routes)
        reports = sweep_repo("OpenVoiceOS", "ovos-skill-alerts", api, compare_content=False)
        self.assertEqual(1, len(reports))
        self.assertEqual(DELETE, reports[0].action)
        self.assertEqual(MERGED, reports[0].reason)
        self.assertEqual([161], reports[0].pulls)
        self.assertFalse(reports[0].deleted)
        self.assertEqual([], api.deleted)

    def test_apply_deletes_the_finished_ref_and_only_that_one(self):
        finished = "translate/kab/all_day.voc-1787734123"
        live = "translate/kab/new_file.voc-1790999999"
        orphan = "translate/kab-DZ/date.dialog-1786988119"
        repo = "ovos-skill-alerts"
        routes = branch_routes("OpenVoiceOS", repo, ["dev", finished, live, orphan])
        routes[pulls_key("OpenVoiceOS", repo, finished)] = [merged(161)]
        routes[pulls_key("OpenVoiceOS", repo, live)] = [opened(500)]
        routes[pulls_key("OpenVoiceOS", repo, orphan)] = []
        api = FakeApi(routes)
        reports = sweep_repo("OpenVoiceOS", repo, api, apply=True, compare_content=False)

        self.assertEqual(
            [f"repos/OpenVoiceOS/{repo}/git/refs/heads/{finished}"],
            api.deleted,
        )
        by_branch = {r.branch: r for r in reports}
        self.assertTrue(by_branch[finished].deleted)
        self.assertFalse(by_branch[live].deleted)
        self.assertFalse(by_branch[orphan].deleted)
        self.assertEqual(KEEP, by_branch[live].action)
        self.assertEqual(KEEP, by_branch[orphan].action)

    def test_a_refused_delete_is_recorded_and_does_not_stop_the_sweep(self):
        first = "translate/kab/aaa.voc-1"
        second = "translate/kab/bbb.voc-2"
        routes = branch_routes("o", "r", [first, second])
        routes[pulls_key("o", "r", first)] = [merged(1)]
        routes[pulls_key("o", "r", second)] = [merged(2)]
        api = FakeApi(routes, deletes_refused=[f"repos/o/r/git/refs/heads/{first}"])
        reports = sweep_repo("o", "r", api, apply=True, compare_content=False)

        by_branch = {r.branch: r for r in reports}
        self.assertFalse(by_branch[first].deleted)
        self.assertEqual("protected ref", by_branch[first].error)
        self.assertTrue(by_branch[second].deleted)
        self.assertEqual("", by_branch[second].error)

    def test_the_default_branch_is_resolved_when_no_base_is_given(self):
        branch = "translate/kab/all_day.voc-1"
        routes = branch_routes("o", "r", [branch], default_branch="master")
        routes[pulls_key("o", "r", branch)] = [merged(1)]
        routes[f"repos/o/r/compare/master...{branch}"] = {"files": []}
        api = FakeApi(routes)
        reports = sweep_repo("o", "r", api)
        self.assertIs(True, reports[0].paths_on_base)
        self.assertIn(("GET", "repos/o/r"), api.calls)

    def test_an_explicit_base_is_used_without_asking_for_the_default(self):
        branch = "translate/kab/all_day.voc-1"
        routes = branch_routes("o", "r", [branch])
        routes[pulls_key("o", "r", branch)] = [merged(1)]
        routes[f"repos/o/r/compare/main...{branch}"] = {"files": []}
        api = FakeApi(routes)
        sweep_repo("o", "r", api, base="main")
        self.assertNotIn(("GET", "repos/o/r"), api.calls)

    def test_content_is_not_compared_when_the_comparison_is_off(self):
        branch = "translate/kab/all_day.voc-1"
        routes = branch_routes("o", "r", [branch])
        routes[pulls_key("o", "r", branch)] = [merged(1)]
        api = FakeApi(routes)
        reports = sweep_repo("o", "r", api, compare_content=False)
        self.assertIsNone(reports[0].paths_on_base)
        self.assertNotIn(("GET", f"repos/o/r/compare/dev...{branch}"), api.calls)

    def test_differing_content_does_not_stop_a_merged_branch_from_being_deleted(self):
        # A squash merge leaves the branch tip outside the base branch, and a
        # later edit to the file makes the bytes differ. The merge is still
        # the authority.
        branch = "translate/kab/at_time.dialog-1"
        routes = branch_routes("o", "r", [branch])
        routes[pulls_key("o", "r", branch)] = [merged(223)]
        routes[f"repos/o/r/compare/dev...{branch}"] = {
            "files": [{"filename": "locale/kab/dialog/at_time.dialog"}]
        }
        routes['repos/o/r/contents/locale/kab/dialog/at_time.dialog?{"ref": "' + branch + '"}'] = {"sha": "a"}
        routes['repos/o/r/contents/locale/kab/dialog/at_time.dialog?{"ref": "dev"}'] = {"sha": "b"}
        api = FakeApi(routes)
        reports = sweep_repo("o", "r", api, apply=True)
        self.assertIs(False, reports[0].paths_on_base)
        self.assertTrue(reports[0].deleted)

    def test_reports_come_back_in_branch_order(self):
        names = ["translate/kab/ccc.voc-3", "translate/kab/aaa.voc-1", "translate/kab/bbb.voc-2"]
        routes = branch_routes("o", "r", names)
        for name in names:
            routes[pulls_key("o", "r", name)] = [merged(1)]
        reports = sweep_repo("o", "r", FakeApi(routes), compare_content=False)
        self.assertEqual(sorted(names), [r.branch for r in reports])


class TestFormatReports(unittest.TestCase):
    def test_a_dry_run_states_both_counts(self):
        reports = [
            BranchReport("o/r", "translate/kab/a.voc-1", DELETE, MERGED, [161], True),
            BranchReport("o/r", "translate/kab/b.voc-2", DELETE, CLOSED_UNMERGED, [396], False),
            BranchReport("o/r", "translate/kab/c.voc-3", KEEP, OPEN_PULL, [500], False),
            BranchReport("o/r", "translate/kab/d.voc-4", KEEP, NO_PULL, [], None),
        ]
        text = format_reports(reports, apply=False)
        self.assertIn("4 submission branches found, 2 finished, 2 still needed.", text)
        self.assertIn("0 deleted: this was a dry run. 2 would be deleted.", text)
        self.assertIn("STALE   o/r translate/kab/a.voc-1 -- pull request #161 merged; "
                      "its paths match the base branch", text)
        self.assertIn("KEEP    o/r translate/kab/c.voc-3 -- pull request #500 is open", text)
        self.assertIn("KEEP    o/r translate/kab/d.voc-4 -- no pull request was ever opened "
                      "from this branch; content not compared", text)

    def test_an_applied_sweep_states_what_it_deleted_and_what_it_could_not(self):
        deleted = BranchReport("o/r", "translate/kab/a.voc-1", DELETE, MERGED, [161])
        deleted.deleted = True
        refused = BranchReport("o/r", "translate/kab/b.voc-2", DELETE, MERGED, [162])
        refused.error = "protected ref"
        text = format_reports([deleted, refused], apply=True)
        self.assertIn("2 submission branches found, 2 finished, 0 still needed.", text)
        self.assertIn("1 deleted, 1 refused.", text)
        self.assertIn("DELETED o/r translate/kab/a.voc-1", text)
        self.assertIn("REFUSED o/r translate/kab/b.voc-2", text)
        self.assertIn("protected ref", text)

    def test_an_empty_sweep_reports_zero_found(self):
        text = format_reports([], apply=True)
        self.assertIn("0 submission branches found, 0 finished, 0 still needed.", text)
        self.assertIn("0 deleted, 0 refused.", text)


if __name__ == "__main__":
    unittest.main()
