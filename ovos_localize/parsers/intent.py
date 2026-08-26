"""Parser for Padatious .intent files.

Format: one training utterance per line, with {slot} placeholders and (alt|alt) groups.
"""


from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class IntentParser(BaseParser):
    """Parser for .intent (Padatious) locale files.

    Each line is a training utterance. Supports:
    - ``{entity}`` slot placeholders
    - ``(option1|option2)`` alternation groups
    - ``#`` comment lines
    """

    file_type = "intent"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse .intent file content.

        Args:
            content: Raw file content.
            path: File path for metadata.

        Returns:
            ParsedFile with each utterance as a ParsedLine.
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
            alternatives = self._extract_alternatives(stripped)
            all_slots.update(slots)
            lines.append(ParsedLine(
                line_number=i,
                text=stripped,
                slots=slots,
                alternatives=alternatives,
            ))

        return ParsedFile(
            path=path,
            file_type=self.file_type,
            lines=lines,
            all_slots=sorted(all_slots),
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to .intent format.

        Args:
            parsed: Parsed intent file.

        Returns:
            One utterance per line.
        """
        return "\n".join(ln.text for ln in parsed.lines if ln.text or ln.is_blank) + "\n"

    @staticmethod
    def compute_diversity(lines: list[ParsedLine]) -> float:
        """Compute lexical diversity score for intent training utterances.

        Diversity is the ratio of unique trigrams to total trigrams across
        all content lines. Higher values indicate more varied phrasings.

        Args:
            lines: Parsed content lines (non-comment, non-blank).

        Returns:
            Float between 0.0 and 1.0.
        """
        content = [ln for ln in lines if not ln.is_comment and not ln.is_blank]
        if not content:
            return 0.0

        all_trigrams: list = []
        unique_trigrams: set = set()
        for ln in content:
            words = ln.text.lower().split()
            for j in range(len(words) - 2):
                trigram = tuple(words[j:j + 3])
                all_trigrams.append(trigram)
                unique_trigrams.add(trigram)

        if not all_trigrams:
            return 1.0
        return len(unique_trigrams) / len(all_trigrams)
