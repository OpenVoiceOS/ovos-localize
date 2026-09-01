"""Unit tests for the single-file submission validator used by the
translation-submission workflow.
"""

from ovos_localize.cli.validate_submission import validate_submission


def test_slot_only_entity_line_rejected(capsys) -> None:
    """A submitted .entity file with a slot-only line is rejected (exit 1)."""
    content = "today\ntomorrow\nyesterday\nnow\n{date}\n"
    code = validate_submission(content, "locale/kab/date.entity")
    assert code == 1
    assert "slot_only_line" in capsys.readouterr().out


def test_normal_entity_content_passes() -> None:
    """A submission with only literal examples is accepted (exit 0)."""
    content = "today\ntomorrow\nyesterday\nnow\nnext week\n"
    code = validate_submission(content, "locale/kab/date.entity")
    assert code == 0


def test_slot_anchored_by_words_passes() -> None:
    """A slot preceded/followed by literal words is fine."""
    content = "play {song} by {artist}\n"
    code = validate_submission(content, "locale/kab/play.intent")
    assert code == 0


def test_slot_only_dialog_line_passes() -> None:
    """A bare {slot} dialog line is legal (ovos-skill-alerts at_time.dialog)."""
    code = validate_submission("{begin}\n", "locale/kab/at_time.dialog")
    assert code == 0


def test_unrecognized_extension_passes() -> None:
    """Unknown file types are not this validator's concern."""
    code = validate_submission("anything", "locale/kab/notes.txt")
    assert code == 0
