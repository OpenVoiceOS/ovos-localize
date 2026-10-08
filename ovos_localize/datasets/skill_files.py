"""Read the per-skill files the data generator writes to ``data/skills/``.

A skill whose JSON exceeds the size cap is written as a main file that keeps
the metadata and lists its ``chunks``, plus one ``<id>_<n>.json`` file per
chunk holding part of ``files``. A chunk is part of a skill, not a skill, so
every reader goes through :func:`load_skills`, which merges the chunks back
into the skill that lists them.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def load_skills(skills_dir: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(skill_id, skill_data)`` for every skill, chunks merged in.

    The skill id is the main file's name without ``.json``. A chunk holds
    ``files`` and nothing else, so a file without a ``repo`` key is never
    yielded on its own. ``X.json`` sorts before ``X_0.json``, so a main file
    is read before its chunks and each file is parsed once.

    Args:
        skills_dir: The ``data/skills`` directory.

    Yields:
        The skill id and the skill data with every chunk's files merged.
    """
    merged: set[str] = set()
    for path in sorted(skills_dir.glob("*.json")):
        if path.name in merged:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "repo" not in data:
            continue
        for name in data.get("chunks", []):
            chunk = json.loads((skills_dir / name).read_text(encoding="utf-8"))
            data["files"].update(chunk["files"])
            merged.add(name)
        yield path.stem, data
