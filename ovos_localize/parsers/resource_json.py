"""Parser for generic JSON resource/data files in locale directories.

Handles key-value JSON files where values are translatable strings or
lists of strings (e.g., color names, yes/no synonyms).
"""

import json

from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine


class ResourceJsonParser(BaseParser):
    """Parser for translatable JSON data files.

    Handles two common formats:
    - ``{"key": "value"}`` — key-to-string mappings (e.g., color names)
    - ``{"key": ["a", "b"]}`` — key-to-list mappings (e.g., yes/no synonyms)
    """

    file_type = "resource_json"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse a resource JSON file.

        Args:
            content: Raw JSON string.
            path: File path for metadata.

        Returns:
            ParsedFile with each value as a ParsedLine.
        """
        lines: list[ParsedLine] = []
        errors: list[str] = []

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
            if isinstance(value, list):
                for j, item in enumerate(value):
                    lines.append(ParsedLine(
                        line_number=line_num + j,
                        text=str(item),
                        metadata={"key": key, "index": j, "translatable": True},
                    ))
                line_num += len(value)
            else:
                lines.append(ParsedLine(
                    line_number=line_num,
                    text=str(value),
                    metadata={"key": key, "translatable": True},
                ))

        return ParsedFile(
            path=path, file_type=self.file_type, lines=lines,
            metadata={"raw_json": data},
        )

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to JSON.

        Args:
            parsed: Parsed resource JSON file.

        Returns:
            Formatted JSON string.
        """
        data = parsed.metadata.get("raw_json", {}).copy()
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
