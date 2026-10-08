"""The one label function every intent corpus builder calls.

A corpus label is ``<skill_id>:<intent_name>`` exactly as the skill registers
it on the bus (OVOS-INTENT-4 §3.2). The skill id is the id the repository's
entry point declares, never the repository's name: ``ovos-skill-easter-eggs``
is a repository, ``skill-easter-eggs.openvoiceos`` is the skill. A train row
and a gold row for one intent must carry one label, so both sides of the
corpus read the id here. The module is the same function the ovos-m2v-pipeline
builder uses (``train/skill_labels.py``), so a label means the same thing in
both repositories. No rename map and no spelling fallback lives here: a gold
label that the train side does not carry is a naming defect to fix in the
skill, not something a reader papers over.
"""
import re
import subprocess
from pathlib import Path

_ENTRY_KEY_RE = re.compile(r'^\s*"?([A-Za-z0-9_.\-]+\.[A-Za-z0-9_\-]+)"?\s*=', re.M)
_PYPROJECT_GROUP_RE = re.compile(r'entry-points\."([^"]+)"')
_SETUP_GROUP_RE = re.compile(r'["\']((?:ovos|opm|mycroft|neon)\.[A-Za-z0-9_.\-]+)["\']\s*:')
#: The entry point groups a skill registers under. Anything else is a plugin.
SKILL_GROUPS = ("ovos.plugin.skill", "opm.skill")
_URL_RE = re.compile(r'https?://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)')


def git_show(repo: Path, rev: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"],
        check=True, capture_output=True, text=True).stdout


def skill_id_from_repo(repo: Path, rev: str, repo_name: str | None = None) -> str:
    """The skill id the repo's entry point declares at *rev*.

    pyproject declares it literally. setup.py derives it from the GitHub URL
    as ``<repo-name>.<author>``, both lowercased, so it is read back the same
    way rather than executed. When the repo declares no entry point at all,
    *repo_name* (when given) stands in as ``<repo_name>.openvoiceos`` so a
    fixture without packaging still builds; a caller that passes it must
    report the assumption. Without *repo_name* an undeclared id is an error.
    """
    try:
        toml = git_show(repo, rev, "pyproject.toml")
    except subprocess.CalledProcessError:
        toml = ""
    for group in ("ovos.plugin.skill", "opm.skill"):
        marker = f'entry-points."{group}"'
        if marker not in toml:
            continue
        tail = toml.split(marker, 1)[1]
        m = _ENTRY_KEY_RE.search(tail.split("[", 1)[0] if "[" in tail else tail)
        if m:
            return m.group(1).lower()
    try:
        setup = git_show(repo, rev, "setup.py")
    except subprocess.CalledProcessError:
        setup = ""
    skill_id = _entry_point_from_setup(setup)
    if skill_id:
        return skill_id
    m = _URL_RE.search(setup or toml)
    if m and "{" not in m.group(2):
        return f"{m.group(2).lower()}.{m.group(1).lower()}"
    if repo_name:
        return f"{repo_name}.openvoiceos"
    raise SystemExit(f"[registry] cannot determine skill_id for {repo} at {rev}")


def entry_point_groups(repo: Path, rev: str) -> list:
    """The plugin entry point groups the repo's packaging registers at *rev*.

    pyproject declares each group as an ``entry-points."<group>"`` table.
    setup.py passes a dict to ``entry_points``, keyed by group, so a quoted
    ``ovos.``/``opm.`` name followed by a colon is read back as a group.
    """
    groups = set()
    for path, pattern in (("pyproject.toml", _PYPROJECT_GROUP_RE),
                          ("setup.py", _SETUP_GROUP_RE)):
        try:
            text = git_show(repo, rev, path)
        except subprocess.CalledProcessError:
            continue
        groups.update(pattern.findall(text))
    groups.discard("console_scripts")
    return sorted(groups)


def declares_skill_id(repo: Path, rev: str) -> bool:
    """True when the repo's packaging names its skill id (so no assumption
    from the repository name was needed)."""
    try:
        return skill_id_from_repo(repo, rev) is not None
    except SystemExit:
        return False


def _entry_point_from_setup(setup: str):
    """The left-hand side of ``PLUGIN_ENTRY_POINT``, resolved statically.

    Skills build the entry point from module-level string constants, often
    derived from the GitHub URL. Those few forms are read back rather than
    executed - importing a skill's setup.py to learn its id is not something
    a dataset builder should do.
    """
    if "PLUGIN_ENTRY_POINT" not in setup:
        return None
    env = dict(re.findall(r"^([A-Z_]+)\s*=\s*f?['\"]([^'\"]+)['\"]", setup, re.M))
    url = _URL_RE.search(env.get("URL", ""))
    if url:
        author, repo = url.group(1), url.group(2)
        # `AUTHOR, NAME = URL.split(".com/")[-1].split("/")`
        m = re.search(r"^([A-Z_]+),\s*([A-Z_]+)\s*=\s*URL\.split", setup, re.M)
        if m:
            env[m.group(1)], env[m.group(2)] = author, repo
        # `NAME = URL.split("/")[-1]`
        for name in re.findall(r'^([A-Z_]+)\s*=\s*URL\.split\(["\']/["\']\)\[-1\]',
                                setup, re.M):
            env[name] = repo
    m = re.search(r"PLUGIN_ENTRY_POINT\s*=\s*\(?\s*f?['\"]([^'\"]*?)=", setup, re.S)
    if not m:
        return None

    placeholder = re.compile(r"\{([A-Z_]+)(?:\.lower\(\))?\}")

    def sub(match, strict=True):
        value = env.get(match.group(1))
        if value is None:
            if not strict:
                return match.group(0)
            raise SystemExit(
                f"[registry] unresolved {match.group(1)!r} in PLUGIN_ENTRY_POINT")
        return value.lower() if ".lower()" in match.group(0) else value

    # constants may be defined in terms of each other; settle them first.
    # A constant that stays unresolved here only matters if the entry point's
    # left-hand side actually references it.
    for _ in range(4):
        if not any(placeholder.search(v) for v in env.values()):
            break
        env = {k: placeholder.sub(lambda mm: sub(mm, False), v)
               for k, v in env.items()}
    skill_id = placeholder.sub(sub, m.group(1)).lower()
    if "{" in skill_id:
        raise SystemExit(f"[registry] could not resolve PLUGIN_ENTRY_POINT "
                         f"to a literal skill id, got {skill_id!r}")
    return skill_id


def intent_name(resource_name: str) -> str:
    """The intent name a resource file registers: its base name, without the
    ``.intent`` suffix a gold file may still write."""
    name = str(resource_name).strip()
    if name.endswith(".intent"):
        name = name[: -len(".intent")]
    return name


def label(skill_id: str, intent: str) -> str:
    """``<skill_id>:<intent_name>``, the form the skill registers on the bus."""
    return f"{skill_id}:{intent_name(intent)}"
