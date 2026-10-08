"""What a skill clone records for the intents corpus, read at scan time.

The data generator scans every repository in ``skills.txt`` and writes one
JSON file per repository. The intents corpus is exported from those files
alone, so everything the corpus needs beyond the locale lines is read here,
from the same clone at the same commit:

* the commit the scan read, so every row names its source revision;
* the plugin entry point groups the packaging registers, which decide whether
  the repository is a skill (``ovos.plugin.skill``) or a plugin;
* the skill id the entry point declares, the left half of every label;
* the golden utterance files of the end-to-end suite, the test side;
* for each ``.intent`` line, the commit that last wrote it, which is the only
  provenance record the fleet keeps.
"""
import json
import re
import subprocess
from pathlib import Path

from ovos_localize.corpus import labels

#: Gold lives beside the end-to-end suite that reads it.
GOLD = re.compile(r"(?:^|.*/)golden_utterances(?:_([A-Za-z-]+))?\.jsonl$")

#: A line a person submitted through ovos-localize lands in a commit whose
#: subject is ``translate(<lang>): ...``; that is the submission convention.
NATIVE_SUBJECT = re.compile(r"^translate\(")

#: Parts of a commit that make no claim about who wrote a line: the
#: ``translate(<langs>)`` scope, whose language code can read as a word
#: (``mt-MT``), and the ``@handle`` of the person who submitted it.
NOT_A_CLAIM = re.compile(r"translate\([^)]*\)|@[\w-]+")

#: How a commit says a line was written by a machine, in words that name no engine.
MACHINE_TRANSLATION = re.compile(
    r"machine[- ]?(?:translat|draft|authored|generated)|by machine|"
    r"auto(?:matic(?:ally)?)?[- ]?translat|translated automatically|"
    r"\b(?:auto|llm|ai|bot|mt)[- ]?generated\b|\bgenerated (?:by|with|via|using)\b|"
    r"\bllms?\b|\bbot[- ](?:output|draft|translat)|\bsynthetic\b|(?-i:\bMT\b)",
    re.IGNORECASE)

#: Translation engines a commit message can name. Naming one says a machine wrote the line.
MT_ENGINES = ("agentpipe", "linguonnx", "nllb", "opus-mt", "marian", "argos",
              "libretranslate", "deepl", "google translate")

#: Each engine as a word, with ``-``, a space or nothing between its parts.
ENGINE_PATTERNS = tuple(
    (engine, re.compile(r"(?<!\w)" + r"[- ]?".join(map(re.escape, re.split(r"[- ]", engine)))
                        + r"(?:s|d)?(?!\w)", re.IGNORECASE))
    for engine in MT_ENGINES)

UNRECORDED_ENGINE = "unrecorded"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def classify_commit(subject: str, message: str) -> tuple:
    """``(provenance, mt_engine)`` for a line last written by this commit.

    ``machine_translation`` where the subject or message names an engine of
    ``MT_ENGINES`` or says in other words that a machine wrote the line, with
    the engine it names, or ``unrecorded``; this wins over the submission
    convention. ``native`` only where the commit follows the
    ovos-localize submission convention and does not say a machine wrote it. Everything
    else is ``unknown``: a line is never native by default.
    """
    text = NOT_A_CLAIM.sub(" ", f"{subject}\n{message}")
    engine = next((name for name, pattern in ENGINE_PATTERNS if pattern.search(text)), None)
    if engine or MACHINE_TRANSLATION.search(text):
        return "machine_translation", engine or UNRECORDED_ENGINE
    if NATIVE_SUBJECT.match(subject):
        return "native", None
    return "unknown", None


def line_provenance(repo: Path, relative_path: str, messages: dict) -> dict:
    """Line number to ``(provenance, mt_engine)`` for one file at HEAD.

    *messages* caches the full message of each commit across files.
    """
    out = {}
    blame = _git(repo, "blame", "--line-porcelain", "HEAD", "--", relative_path)
    sha = subject = None
    line_no = 0
    for line in blame.splitlines():
        if line.startswith("\t"):
            if sha not in messages:
                messages[sha] = _git(repo, "log", "-1", "--format=%B", sha)
            out[line_no] = classify_commit(subject or "", messages[sha])
        elif line.startswith("summary "):
            subject = line[len("summary "):]
        else:
            head = line.split(" ")
            if len(head) >= 3 and len(head[0]) == 40:
                sha, line_no = head[0], int(head[2])
    return out


def read_golden(repo: Path) -> list:
    """Every golden utterance file of the clone, its rows parsed as JSON."""
    files = []
    for path in sorted(repo.rglob("golden_utterances*.jsonl")):
        relative = path.relative_to(repo).as_posix()
        if relative.startswith(".git/") or not GOLD.match(relative):
            continue
        rows, unparsable = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                unparsable += 1
        files.append({"path": relative, "rows": rows, "unparsable": unparsable})
    return files


def read_skill_source(repo: Path, repo_name: str) -> dict:
    """The corpus fields of one clone: commit, entry points, skill id, gold.

    ``skill_id`` is null for a repository that registers no skill entry point.
    """
    groups = labels.entry_point_groups(repo, "HEAD")
    skill_id = None
    if any(group in labels.SKILL_GROUPS for group in groups):
        skill_id = labels.skill_id_from_repo(repo, "HEAD", repo_name)
    return {
        "commit": _git(repo, "rev-parse", "HEAD").strip(),
        "entry_points": groups,
        "skill_id": skill_id,
        "golden": read_golden(repo),
    }
