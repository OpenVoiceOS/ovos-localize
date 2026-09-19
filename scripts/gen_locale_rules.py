"""Write ``data/locale_rules.json``, the table the page reads.

The page cannot run ``langcodes``, so it reads the answer instead of the
rule. This script builds that answer from the same functions the submission
guard uses, over every tag the platform may be asked to write:

* the enabled languages of ``data/coverage.json``;
* every locale directory name in ``data/skills/*.json``, because a
  repository writes tags the enabled list does not carry (``kab-dz``,
  ``en-us``);
* ``config/extra_language_tags.txt``, for a tag that reaches the page by
  link before any repository ships it.

Run it after a language is enabled or a skill is added:

    python scripts/gen_locale_rules.py

``test/unittests/test_locale_rules.py`` fails when the committed file no
longer matches, so a stale table cannot ship.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ovos_localize.locale_rules import build_locale_rules, locale_root_index  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def collect_tags(root: Path) -> set:
    """Collect every language tag the platform may write.

    Args:
        root: The repository root.

    Returns:
        The tags, as written by their source.
    """
    tags = set()

    coverage = root / "data" / "coverage.json"
    if coverage.is_file():
        tags |= set(json.loads(coverage.read_text(encoding="utf-8")).get("languages") or [])

    for manifest in sorted((root / "data" / "skills").glob("*.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for file_data in (data.get("files") or {}).values():
            for lang, entry in (file_data.get("langs") or {}).items():
                tags.add(lang)
                parts = str(entry.get("file_path") or "").split("/")
                # The same root selection the guard and the page use, so a
                # nested res/locale tree does not record "locale" as a tag.
                idx = locale_root_index(parts)
                if idx != -1:
                    tags.add(parts[idx + 1])

    extra = root / "config" / "extra_language_tags.txt"
    if extra.is_file():
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                tags.add(line)

    return tags


def main(argv: list | None = None) -> int:
    """Write the table.

    Args:
        argv: Command line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Exit code. 1 when ``--check`` finds the committed file stale.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="repository root")
    parser.add_argument("--check", action="store_true",
                        help="report whether the committed file is current, write nothing")
    args = parser.parse_args(argv)

    root = Path(args.root)
    rules = build_locale_rules(collect_tags(root))
    target = root / "data" / "locale_rules.json"
    written = json.dumps(rules, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != written:
            print(f"{target} is stale; run python scripts/gen_locale_rules.py")
            return 1
        print(f"{target} is current, {len(rules['tags'])} tags")
        return 0

    target.write_text(written, encoding="utf-8")
    print(f"wrote {target}, {len(rules['tags'])} tags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
