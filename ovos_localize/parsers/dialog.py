"""Parser for .dialog files.

Format: one response variant per line, with {variable} placeholders.
"""


from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class DialogParser(BaseParser):
    """Parser for .dialog locale files.

    Each line is a response variant that may contain ``{variable}`` placeholders
    filled at runtime by ``speak_dialog()``.
    """

    file_type = "dialog"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .dialog file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each variant as a ParsedLine.
        """
        lines: list[ParsedLine] = []
        all_slots: set = set()

        for i, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                lines.append(ParsedLine(line_number=i, text="", is_blank=True))
                continue
            if self._is_comment(stripped):
                lines.append(ParsedLine(line_number=i, text=stripped, is_comment=True))
                continue

            slots = self._extract_slots(stripped)
            all_slots.update(slots)
            lines.append(ParsedLine(
                line_number=i,
                text=stripped,
                slots=slots,
            ))

        return ParsedFile(
            path=path,
            file_type=self.file_type,
            lines=lines,
            all_slots=sorted(all_slots),
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .dialog format.

        Args:
            parsed: Parsed dialog file.

        Returns:
            One variant per line.
        """
        return "\n".join(ln.text for ln in parsed.lines if ln.text or ln.is_blank) + "\n"
