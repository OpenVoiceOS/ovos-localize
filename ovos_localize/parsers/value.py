"""Parser for .value files.

Format: CSV with ``display_name,system_value`` per line.
The right column (system_value) is immutable during translation.
"""


from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class ValueParser(BaseParser):
    """Parser for .value (named value) locale files.

    Each line is ``display_name,system_value``. The system_value (right column)
    must not be modified during translation.
    """

    file_type = "value"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .value file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each mapping as a ParsedLine. Metadata contains
            ``display`` and ``system_value`` keys.
        """
        lines: list[ParsedLine] = []
        errors: list[str] = []

        for i, raw_line in enumerate(content.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped:
                lines.append(ParsedLine(line_number=i, text="", is_blank=True))
                continue
            if self._is_comment(stripped):
                lines.append(ParsedLine(line_number=i, text=stripped, is_comment=True))
                continue

            parts = stripped.split(",", 1)
            if len(parts) != 2:
                errors.append(f"Line {i}: Expected 'display,value' format, got: {stripped}")
                lines.append(ParsedLine(
                    line_number=i, text=stripped,
                    metadata={"display": stripped, "system_value": ""},
                ))
                continue

            display, system_value = parts[0].strip(), parts[1].strip()
            lines.append(ParsedLine(
                line_number=i,
                text=stripped,
                metadata={"display": display, "system_value": system_value},
            ))

        return ParsedFile(
            path=path, file_type=self.file_type, lines=lines, errors=errors
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .value format.

        Args:
            parsed: Parsed value file.

        Returns:
            CSV lines.
        """
        output = []
        for ln in parsed.lines:
            if ln.is_blank:
                output.append("")
            elif ln.is_comment:
                output.append(ln.text)
            elif "display" in ln.metadata and "system_value" in ln.metadata:
                output.append(f"{ln.metadata['display']},{ln.metadata['system_value']}")
            else:
                output.append(ln.text)
        return "\n".join(output) + "\n"
