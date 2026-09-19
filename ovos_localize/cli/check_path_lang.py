"""CLI entry point used by the translation-submission workflow.

Checks that the ``file_path`` of a ``TRANSLATION_META`` block is written to
the locale directory of the submitted ``lang``. A submission whose path names
another language writes the translation over that language's file, which is
how four Kabyle files landed in ovos-date-parser's ``locale/fr/`` tree.

A region-less directory is refused for a regional tag when the project
supports another region of that language, because ``locale/pt/`` names
neither ``pt-BR`` nor ``pt-PT`` and the first submission to reach it would
be written over by the next.
"""

import argparse
import sys

from ovos_localize.lang_utils import check_path_lang, load_supported_langs


def main(argv: list[str] | None = None) -> int:
    """Run the path-against-language check.

    Args:
        argv: Command line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Exit code (0 = path and language agree, 1 = they do not).
    """
    parser = argparse.ArgumentParser(description="Check a submitted file path against its language tag.")
    parser.add_argument("file_path", help="file_path value from the TRANSLATION_META block")
    parser.add_argument("--lang", required=True, help="lang value from the TRANSLATION_META block")
    parser.add_argument(
        "--languages-file",
        help="path to data/coverage.json, which lists every supported tag. Without it a "
             "regional tag against a region-less locale directory is refused, because "
             "whether another region shares that directory cannot be answered.",
    )
    args = parser.parse_args(argv)

    supported = load_supported_langs(args.languages_file) if args.languages_file else None
    problem = check_path_lang(args.file_path, args.lang, supported)
    if problem:
        print(f"[ERROR] {problem}")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
