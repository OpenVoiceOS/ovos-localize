"""CLI entry point used by the translation-submission workflow.

Checks that the ``file_path`` of a ``TRANSLATION_META`` block is written to
the locale directory of the submitted ``lang``. A submission whose path
names another language writes the translation over that language's file,
which is how four Kabyle files landed in ovos-date-parser's ``locale/fr/``
tree.

The answer comes from ``data/locale_rules.json``, the table the page reads,
so the page cannot compose a path this refuses.

Exit codes:

0
    The path names the submitted language.
1
    It does not. The message says why, and the workflow labels the issue.
3
    The rules table is missing or unreadable. That is a platform error and
    not the translator's path: the workflow fails the run and labels
    nothing.
"""

import argparse
import sys

from ovos_localize.locale_rules import OK, check_path_lang, load_locale_rules

SETUP_ERROR = 3


def main(argv: list[str] | None = None) -> int:
    """Run the path-against-language check.

    Args:
        argv: Command line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Exit code, as listed in the module docstring.
    """
    parser = argparse.ArgumentParser(description="Check a submitted file path against its language tag.")
    parser.add_argument("file_path", help="file_path value from the TRANSLATION_META block")
    parser.add_argument("--lang", required=True, help="lang value from the TRANSLATION_META block")
    parser.add_argument(
        "--rules-file", required=True,
        help="path to data/locale_rules.json, the table scripts/gen_locale_rules.py writes "
             "and the page reads",
    )
    args = parser.parse_args(argv)

    try:
        rules = load_locale_rules(args.rules_file)
    except (OSError, ValueError) as error:
        print(f"[SETUP] cannot read the locale rules at {args.rules_file}: {error}")
        print("[SETUP] this is a platform error, not a problem with the submission")
        return SETUP_ERROR

    reason, message = check_path_lang(args.file_path, args.lang, rules)
    if reason != OK:
        print(f"[ERROR] {reason}: {message}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
