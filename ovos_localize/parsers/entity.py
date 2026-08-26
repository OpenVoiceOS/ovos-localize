"""Parser for .entity files.

Format: one example value per line.
"""


from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class EntityParser(BaseParser):
    """Parser for .entity locale files.

    Each line is an example value for a Padatious entity slot.
    """

    file_type = "entity"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .entity file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each example as a ParsedLine.
        """
        lines: list[ParsedLine] = []

        for i, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                lines.append(ParsedLine(line_number=i, text="", is_blank=True))
                continue
            if self._is_comment(stripped):
                lines.append(ParsedLine(line_number=i, text=stripped, is_comment=True))
                continue
            lines.append(ParsedLine(line_number=i, text=stripped))

        return ParsedFile(path=path, file_type=self.file_type, lines=lines)

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .entity format.

        Args:
            parsed: Parsed entity file.

        Returns:
            One example per line.
        """
        return "\n".join(ln.text for ln in parsed.lines if ln.text or ln.is_blank) + "\n"
