"""Base parser interface for OVOS locale files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ParsedLine:
    """A single parsed line from a locale file.

    Attributes:
        line_number: 1-based line number in the file.
        text: The raw text content of the line.
        is_comment: Whether this line is a comment.
        is_blank: Whether this line is empty/whitespace.
        slots: Named slots/variables found in this line (e.g., {location}).
        alternatives: Groups of alternatives found (e.g., (a|b)).
        metadata: Parser-specific metadata for this line.
    """

    line_number: int
    text: str
    is_comment: bool = False
    is_blank: bool = False
    slots: List[str] = field(default_factory=list)
    alternatives: List[List[str]] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedFile:
    """Result of parsing a locale file.

    Attributes:
        path: Path to the source file.
        file_type: The OVOS file type (intent, voc, dialog, etc.).
        lines: Parsed lines.
        all_slots: Union of all slots found across all lines.
        errors: Parsing errors encountered.
        metadata: Parser-specific file-level metadata.
    """

    path: str
    file_type: str
    lines: List[ParsedLine] = field(default_factory=list)
    all_slots: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def content_lines(self) -> List[ParsedLine]:
        """Return only non-comment, non-blank lines."""
        return [ln for ln in self.lines if not ln.is_comment and not ln.is_blank]

    @property
    def line_count(self) -> int:
        """Return number of content lines."""
        return len(self.content_lines)


class BaseParser:
    """Base class for all locale file parsers.

    Subclasses must implement ``parse_content`` and ``serialize``.
    """

    file_type: str = ""

    def parse(self, path: str) -> ParsedFile:
        """Parse a locale file from disk.

        Args:
            path: Path to the file.

        Returns:
            ParsedFile with all lines parsed.
        """
        content = Path(path).read_text(encoding="utf-8")
        return self.parse_content(content, path)

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse locale file content from a string.

        Args:
            content: File content as string.
            path: Optional path for metadata.

        Returns:
            ParsedFile with all lines parsed.
        """
        raise NotImplementedError

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize a parsed file back to its native format.

        Args:
            parsed: The parsed file to serialize.

        Returns:
            File content as string.
        """
        raise NotImplementedError

    @staticmethod
    def _extract_slots(text: str) -> List[str]:
        """Extract {slot_name} placeholders from text.

        Args:
            text: Line text to scan.

        Returns:
            List of slot names found.
        """
        import re
        # Match {name} but not {{name}} (escaped braces)
        return re.findall(r"(?<!\{)\{(\w+)\}(?!\})", text)

    @staticmethod
    def _extract_alternatives(text: str) -> List[List[str]]:
        """Extract (alt1|alt2|alt3) groups from text.

        Args:
            text: Line text to scan.

        Returns:
            List of alternative groups, each a list of options.
        """
        import re
        groups = re.findall(r"\(([^)]+)\)", text)
        result = []
        for group in groups:
            if "|" in group:
                result.append([opt.strip() for opt in group.split("|")])
        return result

    @staticmethod
    def _is_comment(line: str) -> bool:
        """Check if a line is a comment.

        Args:
            line: Raw line text.

        Returns:
            True if the line starts with #.
        """
        return line.strip().startswith("#")
