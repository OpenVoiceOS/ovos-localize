"""Translation submission payload contract (B3.1 — session/batch editing).

An issue created by the SPA carries either:

* **v1** — a single ``<!-- TRANSLATION_META … -->`` block plus one
  ``<content>…</content>`` (base64), i.e. one file; or
* **v2** — a ``<!-- SESSION_META … -->`` block whose JSON body is
  ``{"meta_version": 2, "entries": [ … ]}``, i.e. a whole editing session of
  many files across many repos.

Both shapes parse into a common list of :class:`Entry`, grouped per target
repository so each gets one pull request.

The single-file flow in ``submit_translation.yml`` does its own parsing and
validation today; this module is the contract the session flow needs before it
can be wired up, and holds the same rules in testable form. Issue bodies are
written by anyone, so nothing here trusts a field it has not checked.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Locale resource file suffixes we allow a submission to write.
MAX_ENTRIES = 200
"""One session cannot open an unbounded number of pull requests."""

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

ALLOWED_SUFFIXES = (
    ".intent", ".voc", ".dialog", ".entity", ".rx", ".value",
    ".json", ".list",
)

_META_V1 = re.compile(r"<!--\s*TRANSLATION_META\s+([\s\S]*?)-->")
_META_V2 = re.compile(r"<!--\s*SESSION_META\s+([\s\S]*?)-->")
_CONTENT = re.compile(r"<content>([\s\S]*?)</content>")


class SubmissionError(ValueError):
    """Raised when an issue body cannot be parsed into valid entries."""


@dataclass
class Entry:
    """One file to write into one target repo."""

    org: str
    repo: str
    branch: str
    file_path: str
    lang: str
    file_key: str
    content_b64: str = ""

    @property
    def repo_key(self) -> tuple[str, str]:
        return (self.org, self.repo)


def _parse_meta_block(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.strip().splitlines():
        key, sep, rest = line.partition(":")
        if sep and key.strip():
            meta[key.strip()] = rest.strip()
    return meta


def _entry_from_dict(d: dict) -> Entry:
    try:
        return Entry(
            org=str(d["org"]).strip(),
            repo=str(d["repo"]).strip(),
            branch=str(d.get("branch", "dev")).strip() or "dev",
            file_path=str(d["file_path"]).strip(),
            lang=str(d["lang"]).strip(),
            file_key=str(d.get("file_key", "")).strip(),
            content_b64=str(d.get("content_b64", "")).strip(),
        )
    except KeyError as exc:
        raise SubmissionError(f"entry missing required field: {exc}") from exc


def parse_issue_body(body: str) -> list[Entry]:
    """Parse an issue body into a list of :class:`Entry`, v1 or v2.

    Raises:
        SubmissionError: if neither a v1 nor v2 payload can be found.
    """
    body = body or ""

    m2 = _META_V2.search(body)
    if m2:
        try:
            payload = json.loads(m2.group(1).strip())
        except json.JSONDecodeError as exc:
            raise SubmissionError(f"SESSION_META is not valid JSON: {exc}") from exc
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, list) or not entries:
            raise SubmissionError("SESSION_META has no entries")
        return [_entry_from_dict(e) for e in entries]

    m1 = _META_V1.search(body)
    if m1:
        meta = _parse_meta_block(m1.group(1))
        content = _CONTENT.search(body)
        meta["content_b64"] = content.group(1).strip() if content else ""
        return [_entry_from_dict(meta)]

    raise SubmissionError("no TRANSLATION_META or SESSION_META block found")


def is_safe_path(file_path: str) -> bool:
    """True if ``file_path`` names a translatable resource in a locale tree.

    An issue body is written by anyone, and whatever it names here is what
    gets written and committed. Rejecting traversal is not enough on its own:
    ``package.json`` and ``renovate.json`` contain no ``..`` and end in an
    allowed suffix, so the path must also be anchored to a locale directory.

    The locale root may sit inside a package directory, and resource names may
    contain spaces, so both are permitted.
    """
    if not file_path or file_path.startswith("/") or "\\" in file_path or "\0" in file_path:
        return False
    if not file_path.endswith(ALLOWED_SUFFIXES):
        return False
    parts = file_path.split("/")
    if any(p in ("", ".", "..", ".github") for p in parts):
        return False
    try:
        root = next(i for i, p in enumerate(parts) if p in ("locale", "res"))
    except StopIteration:
        return False
    # a language directory and a file must follow the locale root
    if len(parts) < root + 3:
        return False
    return bool(_LANG_RE.match(parts[root + 1]))


def validate_entries(entries: list[Entry]) -> list[Entry]:
    """Return ``entries`` unchanged, or raise if any is unsafe.

    Raises:
        SubmissionError: on a missing org/repo/lang or an unsafe file path.
    """
    if len(entries) > MAX_ENTRIES:
        raise SubmissionError(f"{len(entries)} entries exceeds the {MAX_ENTRIES} allowed in one submission")
    for e in entries:
        if not (e.org and e.repo and e.lang):
            raise SubmissionError(f"entry missing org/repo/lang: {e}")
        if not _NAME_RE.match(e.org) or not _NAME_RE.match(e.repo):
            raise SubmissionError(f"unsafe org/repo: {e.org!r}/{e.repo!r}")
        if not _LANG_RE.match(e.lang):
            raise SubmissionError(f"not a language tag: {e.lang!r}")
        if not is_safe_path(e.file_path):
            raise SubmissionError(f"unsafe or unsupported file path: {e.file_path!r}")
        if not e.content_b64.strip():
            raise SubmissionError(f"empty content for {e.file_path!r}; refusing to blank the file")
    return entries


def group_by_repo(entries: list[Entry]) -> dict[tuple[str, str], list[Entry]]:
    """Group entries by (org, repo) so each target repo gets one PR."""
    grouped: dict[tuple[str, str], list[Entry]] = {}
    for e in entries:
        grouped.setdefault(e.repo_key, []).append(e)
    return grouped
