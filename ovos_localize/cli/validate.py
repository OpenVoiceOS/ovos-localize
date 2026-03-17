"""Standalone CLI validation tool for OVOS locale files.

Usable in CI pipelines and locally without the web server.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

from ovos_localize.parsers import get_parser
from ovos_localize.parsers.base import ParsedFile
from ovos_localize.sync.github import scan_locale_directory
from ovos_localize.validators.rules import ValidationIssue, validate_file


def validate_repo(repo_path: str, report_format: str = "text") -> int:
    """Validate all locale files in a repository.

    Args:
        repo_path: Path to repository root.
        report_format: Output format ('text' or 'github').

    Returns:
        Exit code (0 = pass, 1 = errors found).
    """
    repo = Path(repo_path)
    locale_dir = None
    for candidate in repo.rglob("locale"):
        if candidate.is_dir():
            locale_dir = candidate
            break

    if not locale_dir:
        print("No locale/ directory found.")
        return 0

    scanned_files = scan_locale_directory(str(locale_dir))
    if not scanned_files:
        print("No locale files found.")
        return 0

    # Group by base_name to find source (en-us) files
    sources = {}
    for sf in scanned_files:
        if sf.lang == "en-US" and sf.parsed:
            sources[sf.base_name] = sf.parsed

    total_errors = 0
    total_warnings = 0
    all_issues: List[dict] = []

    for sf in scanned_files:
        if not sf.parsed:
            continue

        source = sources.get(sf.base_name)
        issues = validate_file(sf.parsed, source)

        for issue in issues:
            entry = {
                "file": sf.relative_path,
                "rule": issue.rule_name,
                "severity": issue.severity,
                "message": issue.message,
                "line": issue.line_number,
            }
            all_issues.append(entry)

            if issue.severity == "error":
                total_errors += 1
            elif issue.severity == "warning":
                total_warnings += 1

    if report_format == "github":
        _print_github_format(all_issues)
    elif report_format == "json":
        print(json.dumps(all_issues, indent=2))
    else:
        _print_text_format(all_issues, total_errors, total_warnings)

    return 1 if total_errors > 0 else 0


def _print_text_format(issues: List[dict], errors: int, warnings: int) -> None:
    """Print validation results as human-readable text.

    Args:
        issues: List of issue dicts.
        errors: Error count.
        warnings: Warning count.
    """
    if not issues:
        print("All locale files pass validation.")
        return

    for issue in issues:
        severity = issue["severity"].upper()
        line_str = f":{issue['line']}" if issue["line"] else ""
        print(f"[{severity}] {issue['file']}{line_str} — {issue['rule']}: {issue['message']}")

    print(f"\nTotal: {errors} error(s), {warnings} warning(s)")


def _print_github_format(issues: List[dict]) -> None:
    """Print validation results as GitHub Actions annotations.

    Args:
        issues: List of issue dicts.
    """
    for issue in issues:
        level = "error" if issue["severity"] == "error" else "warning"
        line = issue.get("line", "")
        file = issue["file"]
        msg = f"{issue['rule']}: {issue['message']}"
        if line:
            print(f"::{level} file={file},line={line}::{msg}")
        else:
            print(f"::{level} file={file}::{msg}")


def main() -> None:
    """CLI entry point for ovos-localize-cli validate."""
    parser = argparse.ArgumentParser(
        description="Validate OVOS locale files"
    )
    parser.add_argument(
        "--repo", default=".", help="Path to repository root (default: current dir)"
    )
    parser.add_argument(
        "--report-format",
        choices=["text", "github", "json"],
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    exit_code = validate_repo(args.repo, args.report_format)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
