"""Parser for settingsmeta.json / settingsmeta.yml files."""

import json

from ovos_localize.parsers.base import BaseParser, ParsedFile, ParsedLine

# Keys in settingsmeta that contain translatable text
TRANSLATABLE_FIELDS = {"label", "name", "title", "placeholder", "value"}


class SettingsMetaParser(BaseParser):
    """Parser for settingsmeta.json/yml locale files.

    Only ``label``, ``name``, ``title``, and ``placeholder`` fields are
    translatable. Structure must be preserved exactly.
    """

    file_type = "settingsmeta"

    def parse_content(self, content: str, path: str = "") -> ParsedFile:
        """Parse settingsmeta content.

        Args:
            content: Raw JSON or YAML string.
            path: File path for metadata.

        Returns:
            ParsedFile with translatable fields as ParsedLines.
        """
        lines: list[ParsedLine] = []
        errors: list[str] = []
        data = None

        # Try JSON first, then YAML
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            try:
                import yaml
                data = yaml.safe_load(content)
            except Exception as e:
                errors.append(f"Cannot parse as JSON or YAML: {e}")

        if data is None:
            return ParsedFile(
                path=path, file_type=self.file_type, errors=errors
            )

        line_num = 0
        self._extract_translatable(data, lines, line_num, "")

        return ParsedFile(
            path=path, file_type=self.file_type, lines=lines,
            metadata={"raw_data": data, "format": "json" if path.endswith(".json") else "yaml"},
        )

    def _extract_translatable(
        self, obj: object, lines: list[ParsedLine],
        line_num: int, json_path: str
    ) -> int:
        """Recursively extract translatable fields from settingsmeta structure.

        Args:
            obj: Current object being traversed.
            lines: List to append ParsedLines to.
            line_num: Current line number counter.
            json_path: JSON path to current object for reference.

        Returns:
            Updated line number counter.
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{json_path}.{key}" if json_path else key
                if key in TRANSLATABLE_FIELDS and isinstance(value, str):
                    line_num += 1
                    lines.append(ParsedLine(
                        line_number=line_num,
                        text=value,
                        metadata={
                            "json_path": current_path,
                            "key": key,
                            "translatable": True,
                        },
                    ))
                elif isinstance(value, (dict, list)):
                    line_num = self._extract_translatable(
                        value, lines, line_num, current_path
                    )
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                line_num = self._extract_translatable(
                    item, lines, line_num, f"{json_path}[{i}]"
                )
        return line_num

    def serialize(self, parsed: ParsedFile) -> str:
        """Serialize back to JSON or YAML.

        Args:
            parsed: Parsed settingsmeta file.

        Returns:
            Formatted JSON or YAML string.
        """
        data = parsed.metadata.get("raw_data", {})
        fmt = parsed.metadata.get("format", "json")
        if fmt == "yaml":
            try:
                import yaml
                return yaml.dump(data, default_flow_style=False, allow_unicode=True)
            except ImportError:
                pass
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
