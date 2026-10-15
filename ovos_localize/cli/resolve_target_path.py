"""CLI the translation-submission workflow uses to place a file in the target tree.

The ``file_path`` of a ``TRANSLATION_META`` block is composed by the page when
the translator submits, from the skill inventory of that day. The pull request
is opened later, sometimes weeks later when an issue is re-run, and by then the
skill may have renamed the resource: ovos-skill-laugh#133 renamed ``Stop.voc``
to ``stop.voc`` in every language, and the re-run of ovos-localize#489 then
opened ovos-skill-laugh#137 adding ``kab/vocab/Stop.voc``, a file the skill
never loads.

This entry point checks the path against the checked-out target branch. A
resource is current when some language directory of the same locale root holds
it under the same relative path. When none does, the one resource whose
relative path matches ignoring case is taken instead, which is how a rename to
lowercase is followed. Anything else is refused.

The ``file_key`` names the resource the translator edited, and for a
line-per-value resource its suffix is the resource kind. ovos-localize#490
carries the key ``Laugh.intent`` with the path ``.../Laugh.voc``: its lines are
intent phrases, and written to the path they would become keywords of the
vocabulary the skill matches on. A key whose suffix differs from the path's is
refused. A ``.json`` path is exempt, because its key names the inventory entry
(``99colors.resource_json``) and not a file.

Exit codes:

0
    The path to write is printed on stdout: the submitted one, or the current
    spelling of the same resource.
1
    No language directory holds the resource under any spelling, more than one
    spelling matches, or the key and the path name different resource kinds.
    The message says which, and nothing is written.
"""

import argparse
import sys
from pathlib import Path

LOCALE_ROOTS = ("locale", "res")


class StalePathError(ValueError):
    """The submitted resource does not exist in the target tree."""


def _split(file_path: str) -> tuple[list[str], str, list[str]]:
    parts = file_path.split("/")
    for i, seg in enumerate(parts):
        if seg in LOCALE_ROOTS and len(parts) >= i + 3:
            return parts[: i + 1], parts[i + 1], parts[i + 2:]
    raise StalePathError(f"{file_path} does not sit under a locale or res language directory")


def _suffix(name: str) -> str:
    return Path(name).suffix.lower()


def resolve_target_path(file_path: str, repo_root: str | Path, file_key: str | None = None) -> str:
    """The path the submission belongs at in the target repository's tree.

    Args:
        file_path: ``file_path`` from the ``TRANSLATION_META`` block.
        repo_root: The checkout of the target branch.
        file_key: ``file_key`` from the same block, when there is one.

    Returns:
        ``file_path`` when the resource exists under that relative path in any
        language directory, else the same path with the relative part replaced
        by the one existing spelling that matches it ignoring case.

    Raises:
        StalePathError: No spelling of the resource exists, several do, or
            ``file_key`` names another kind of resource than ``file_path``.
    """
    if file_key and _suffix(file_path) != ".json" and _suffix(file_key) != _suffix(file_path):
        raise StalePathError(f"file_key {file_key} and file_path {file_path} name different kinds of resource")
    root_parts, lang, rel_parts = _split(file_path)
    repo_root = Path(repo_root)
    locale_root = repo_root.joinpath(*root_parts)
    if (repo_root / file_path).is_file():
        return file_path
    if not locale_root.is_dir():
        raise StalePathError(f"{'/'.join(root_parts)} does not exist on the target branch")

    lang_dirs = [d for d in locale_root.iterdir() if d.is_dir()]
    rel = "/".join(rel_parts)
    if any((d / rel).is_file() for d in lang_dirs):
        return file_path

    spellings = sorted({
        p.relative_to(d).as_posix()
        for d in lang_dirs
        for p in d.rglob("*")
        if p.is_file() and p.relative_to(d).as_posix().lower() == rel.lower()
    })
    if len(spellings) == 1:
        return "/".join(root_parts + [lang, spellings[0]])
    if not spellings:
        raise StalePathError(
            f"no language directory under {'/'.join(root_parts)} holds {rel}; "
            "the resource was renamed or removed on the target branch")
    raise StalePathError(f"{rel} matches several resources ignoring case: {', '.join(spellings)}")


def main(argv: list[str] | None = None) -> int:
    """Resolve a submitted path against a checkout of the target branch.

    Args:
        argv: Command line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Exit code, as listed in the module docstring.
    """
    parser = argparse.ArgumentParser(description="Place a submitted file path in the target repository's tree.")
    parser.add_argument("file_path", help="file_path value from the TRANSLATION_META block")
    parser.add_argument("--repo-root", required=True, help="checkout of the target branch")
    parser.add_argument("--file-key", help="file_key value from the TRANSLATION_META block")
    args = parser.parse_args(argv)
    try:
        resolved = resolve_target_path(args.file_path, args.repo_root, args.file_key)
    except StalePathError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    if resolved != args.file_path:
        print(f"[INFO] {args.file_path} is {resolved} on the target branch", file=sys.stderr)
    print(resolved)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
