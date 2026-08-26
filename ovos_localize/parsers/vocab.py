"""Parser for Adapt .voc files.

Format: one keyword per line, with optional (alt|alt) expansion.
"""


from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class VocabParser(BaseParser):
    """Parser for .voc (Adapt keyword) locale files.

    Each line is a keyword or keyword phrase. Supports ``(alt1|alt2)`` expansion.
    """

    file_type = "voc"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .voc file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each keyword as a ParsedLine.
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

            alternatives = self._extract_alternatives(stripped)
            word_count = len(stripped.split())
            lines.append(ParsedLine(
                line_number=i,
                text=stripped,
                alternatives=alternatives,
                metadata={"word_count": word_count},
            ))

        return ParsedFile(path=path, file_type=self.file_type, lines=lines)

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .voc format.

        Args:
            parsed: Parsed vocab file.

        Returns:
            One keyword per line.
        """
        return "\n".join(ln.text for ln in parsed.lines if ln.text or ln.is_blank) + "\n"
