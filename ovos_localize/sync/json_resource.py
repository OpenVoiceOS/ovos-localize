"""Render a submitted translation for a JSON locale resource.

A `.voc` or a `.dialog` file holds one value per line, and the portal's editor
hands the workflow exactly the lines the translator typed. A JSON resource is a
flat object instead: `word_connectors.json` is `{"and": ..., "or": ...}`, and
the same line-per-value payload written straight to that path is not JSON at
all. That happened to Kabyle `word_connectors.json` in ovos-workshop#659, which
committed two bare lines, `d` and `naɣ`, over a `.json` path, so the pull
request the portal had opened could not merge (T-4252).

This module turns a submission into the text that belongs at a `.json` path, or
refuses it. It never guesses a key: the keys come from the file already in the
target repository, in the order that file holds them.
"""

from __future__ import annotations

import json
from collections import OrderedDict


class JsonResourceError(ValueError):
    """Raised when a submission cannot become valid JSON for its path."""


def is_json_resource(file_path: str) -> bool:
    """True when this path must hold JSON."""
    return file_path.lower().endswith(".json")


def render_json_submission(content: str, existing: str | None = None) -> str:
    """The text to write at a ``.json`` path, or raise.

    Two shapes are accepted, and nothing else:

    * The submission is already a JSON object. The editor's key and value form
      sends this, and it is written through unchanged apart from a normalised
      indent and a closing newline.
    * The submission is one value per line, and the file already in the target
      repository is a JSON object with exactly as many keys. The values fill
      the existing keys in the order that file holds them, which is the order
      the editor showed them in.

    Args:
        content: The decoded submission.
        existing: The file already at that path, or None when there is none.

    Returns:
        JSON text, with a closing newline.

    Raises:
        JsonResourceError: when the submission cannot be made into JSON
            without guessing.
    """
    text = (content or "").strip()
    if not text:
        raise JsonResourceError("the submission is empty; refusing to blank a JSON resource")

    # Shape one: the submission is already JSON.
    try:
        data = json.loads(text, object_pairs_hook=OrderedDict)
    except json.JSONDecodeError:
        data = None
    if data is not None:
        if not isinstance(data, dict):
            raise JsonResourceError(
                f"a locale JSON resource is an object of keys and values, not a "
                f"{type(data).__name__}"
            )
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    # Shape two: one value per line, mapped onto the keys already in the file.
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if existing is None:
        raise JsonResourceError(
            "this path holds a JSON object, the submission is neither JSON nor "
            "a line per key, and there is no file in the target repository to "
            "take the keys from. Submit the JSON itself."
        )
    try:
        current = json.loads(existing, object_pairs_hook=OrderedDict)
    except json.JSONDecodeError as exc:
        raise JsonResourceError(
            f"the submission is not JSON, and the file already at this path is "
            f"not JSON either, so there are no keys to fill: {exc}"
        ) from exc
    if not isinstance(current, dict):
        raise JsonResourceError(
            "the file already at this path is not an object of keys and values, "
            "so a line per value cannot be mapped onto it"
        )
    keys = list(current.keys())
    if len(keys) != len(lines):
        raise JsonResourceError(
            f"the submission has {len(lines)} line(s) and the file has "
            f"{len(keys)} key(s) ({', '.join(keys) or 'none'}); a value per key "
            f"is the only mapping that does not guess"
        )
    # A list value takes a list of one: the shape of the key is kept, because a
    # consumer that reads a list must keep reading a list.
    out: OrderedDict = OrderedDict()
    for key, value in zip(keys, lines):
        out[key] = [value] if isinstance(current[key], list) else value
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"
