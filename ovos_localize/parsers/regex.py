"""Parser for .rx (regex) files.

Format: one regex pattern per line, with (?P<Name>...) named groups.
"""

import re

from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class RegexParser(BaseParser):
    """Parser for .rx (regex) locale files.

    Each line is a regex pattern. Named groups ``(?P<Name>...)`` are used
    for entity extraction by the Adapt intent system.
    """

    file_type = "rx"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .rx file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each regex as a ParsedLine. Named groups
            are stored in the ``slots`` field.
        """
        lines: list[ParsedLine] = []
        all_slots: set = set()
        errors: list[str] = []

        for i, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                lines.append(ParsedLine(line_number=i, text="", is_blank=True))
                continue
            if self._is_comment(stripped):
                lines.append(ParsedLine(line_number=i, text=stripped, is_comment=True))
                continue

            named_groups = re.findall(r"\(\?P<(\w+)>", stripped)
            all_slots.update(named_groups)

            # Validate regex compilation
            compiles = True
            try:
                re.compile(stripped)
            except re.error as e:
                compiles = False
                errors.append(f"Line {i}: Invalid regex: {e}")

            lines.append(ParsedLine(
                line_number=i,
                text=stripped,
                slots=named_groups,
                metadata={"compiles": compiles},
            ))

        return ParsedFile(
            path=path,
            file_type=self.file_type,
            lines=lines,
            all_slots=sorted(all_slots),
            errors=errors,
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .rx format.

        Args:
            parsed: Parsed regex file.

        Returns:
            One regex per line.
        """
        return "\n".join(ln.text for ln in parsed.lines if ln.text or ln.is_blank) + "\n"
