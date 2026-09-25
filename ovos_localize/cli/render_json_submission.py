"""CLI the translation-submission workflow uses to write a JSON resource.

The workflow writes a submission to its path with `base64 -d > "$FILE_PATH"`,
which is right for a line-per-value resource and wrong for a `.json` one. This
entry point produces the text that belongs at a `.json` path, or exits 1 with
the reason, so a submission that cannot be made into JSON is refused before a
branch carries it (T-4252).

The keys a line-per-value submission fills come from a file that already holds
them. The target language's own file is the first choice, and for a language
that does not have the file yet, a sibling locale directory is read instead:
that is the file the editor showed the translator, so its keys and their order
are the ones the typed lines are in. English is preferred, and any sibling is
better than a guess.
"""

import argparse
import json
import sys
from pathlib import Path

from ovos_localize.sync.json_resource import JsonResourceError, render_json_submission

# Read in this order when the target language has no file yet.
_PREFERRED_SOURCES = ("en-US", "en-us", "en")


def _is_json_object(path: Path) -> bool:
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def find_key_source(target: Path) -> Path | None:
    """A file whose keys the submission can fill, or None.

    Args:
        target: The path the submission is for, inside ``<locale>/<lang>/``.

    Returns:
        The target file itself when it is there and is a JSON object, else a
        sibling locale directory's file of the same name, English first.
    """
    if _is_json_object(target):
        return target
    lang_dir = target.parent
    locale_root = lang_dir.parent
    if not locale_root.is_dir():
        return None
    siblings = [d for d in sorted(locale_root.iterdir())
                if d.is_dir() and d.name != lang_dir.name]
    preferred = [d for d in siblings if d.name in _PREFERRED_SOURCES]
    for d in preferred + [d for d in siblings if d not in preferred]:
        candidate = d / target.name
        if _is_json_object(candidate):
            return candidate
    return None


def main() -> None:
    """CLI entry point for ``ovos-localize-render-json``."""
    parser = argparse.ArgumentParser(
        description="Render a submitted translation as the JSON its path needs."
    )
    parser.add_argument("--content-file", required=True,
                        help="Path to a file holding the decoded submission")
    parser.add_argument("--existing-file",
                        help="The target path. Its keys, or a sibling locale's, are "
                             "what a line-per-value submission fills")
    parser.add_argument("--out", required=True, help="Where to write the JSON")
    args = parser.parse_args()

    content = Path(args.content_file).read_text(encoding="utf-8")
    existing = None
    source = None
    if args.existing_file:
        source = find_key_source(Path(args.existing_file))
        if source is not None:
            existing = source.read_text(encoding="utf-8")

    try:
        rendered = render_json_submission(content, existing)
    except JsonResourceError as exc:
        print(f"[ERROR] {args.out}: {exc}", file=sys.stderr)
        sys.exit(1)

    if source is not None and source != Path(args.existing_file):
        print(f"keys taken from {source}")
    Path(args.out).write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
