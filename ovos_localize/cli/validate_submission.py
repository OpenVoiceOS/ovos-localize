"""CLI entry point used by the translation-submission workflow.

Validates a single submitted file's content before a PR is opened, without
requiring a full repository checkout. Only errors are fatal here — warnings
(missing en-US source for slot comparison, low line counts, etc.) are not
knowable from a lone submitted file and are left to the target repo's own CI.
"""

import argparse
import sys
from pathlib import Path

from ovos_localize.parsers import get_parser
from ovos_localize.validators.rules import validate_file


def validate_submission(content: str, file_path: str) -> int:
    """Validate submitted file content and print any errors found.

    Args:
        content: Raw file content as submitted.
        file_path: Target path (used to pick a parser by extension).

    Returns:
        Exit code (0 = pass, 1 = errors found).
    """
    parser_cls = get_parser(file_path)
    if parser_cls is None:
        # Unrecognized extension already rejected upstream by the workflow;
        # nothing further to validate here.
        return 0

    parsed = parser_cls().parse_content(content, file_path)
    issues = [i for i in validate_file(parsed) if i.severity == "error"]

    for issue in issues:
        line_str = f":{issue.line_number}" if issue.line_number else ""
        print(f"[ERROR] {file_path}{line_str} — {issue.rule_name}: {issue.message}")

    return 1 if issues else 0


def main() -> None:
    """CLI entry point for ``ovos-localize-cli validate-submission``."""
    parser = argparse.ArgumentParser(
        description="Validate a single submitted locale file before opening a PR."
    )
    parser.add_argument("file_path", help="Target path of the submitted file")
    parser.add_argument(
        "--content-file",
        required=True,
        help="Path to a file holding the decoded submission content",
    )
    args = parser.parse_args()

    content = Path(args.content_file).read_text(encoding="utf-8")
    sys.exit(validate_submission(content, args.file_path))


if __name__ == "__main__":
    main()
