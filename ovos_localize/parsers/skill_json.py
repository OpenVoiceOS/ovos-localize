"""Parser for skill.json metadata files."""

import json
from typing import List

from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine

# Keys in skill.json that are translatable
TRANSLATABLE_KEYS = {"name", "description", "examples", "tags"}


class SkillJsonParser(BaseParser):
    """Parser for skill.json locale files.

    JSON metadata with translatable fields (name, description, examples, tags)
    and non-translatable fields (skill_id, source).
    """

    file_type = "skill.json"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse skill.json content.

        Args:
            content: Raw JSON string.
            path: File path for metadata.

        Returns:
            ParsedFile with each translatable key as a ParsedLine.
        """
        lines: List[ParsedLine] = []
        errors: List[str] = []

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            return ParsedFile(
                path=path, file_type=self.file_type,
                errors=[f"Invalid JSON: {e}"],
            )

        line_num = 0
        for key, value in data.items():
            line_num += 1
            is_translatable = key in TRANSLATABLE_KEYS
            if isinstance(value, list):
                for j, item in enumerate(value):
                    lines.append(ParsedLine(
                        line_number=line_num + j,
                        text=str(item),
                        metadata={
                            "key": key,
                            "index": j,
                            "translatable": is_translatable,
                        },
                    ))
                line_num += len(value)
            else:
                lines.append(ParsedLine(
                    line_number=line_num,
                    text=str(value),
                    metadata={
                        "key": key,
                        "translatable": is_translatable,
                    },
                ))

        return ParsedFile(
            path=path, file_type=self.file_type, lines=lines,
            metadata={"raw_json": data},
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to JSON.

        Args:
            parsed: Parsed skill.json file.

        Returns:
            Formatted JSON string.
        """
        data = parsed.metadata.get("raw_json", {}).copy()
        # Rebuild from parsed lines
        list_keys: dict = {}
        for ln in parsed.lines:
            key = ln.metadata.get("key")
            if not key:
                continue
            if "index" in ln.metadata:
                list_keys.setdefault(key, [])
                list_keys[key].append(ln.text)
            else:
                data[key] = ln.text
        data.update(list_keys)
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
