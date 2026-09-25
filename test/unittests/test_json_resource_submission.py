"""Unit tests for rendering a submission into a JSON locale resource (T-4252).

ovos-workshop#659 committed two bare lines, ``d`` and ``naɣ``, over
``ovos_workshop/locale/kab/word_connectors.json``. The file is a flat JSON
object, so the portal's own pull request could not merge. These tests hold both
halves of the fix: the renderer that turns such a submission into the JSON the
path needs, and the refusal when it cannot without guessing.
"""

import json
from pathlib import Path

import pytest

from ovos_localize.cli.render_json_submission import find_key_source
from ovos_localize.cli.validate_submission import validate_submission
from ovos_localize.sync.json_resource import (
    JsonResourceError,
    is_json_resource,
    render_json_submission,
)

WORD_CONNECTORS_EN = '{\n  "and": "and",\n  "or": "or"\n}\n'
KAB_LINES = "d\nnaɣ\n"


def test_is_json_resource() -> None:
    assert is_json_resource("ovos_workshop/locale/kab/word_connectors.json")
    assert is_json_resource("locale/kab/SETTINGS.JSON")
    assert not is_json_resource("locale/kab/and.voc")


def test_the_659_payload_becomes_the_json_the_path_needs() -> None:
    """The exact submission that broke ovos-workshop#659."""
    out = render_json_submission(KAB_LINES, WORD_CONNECTORS_EN)
    assert json.loads(out) == {"and": "d", "or": "naɣ"}
    assert out.endswith("\n")


def test_the_key_order_is_the_existing_files_order() -> None:
    """The editor shows the values in the file's order, so that is the mapping."""
    existing = '{"or": "or", "and": "and"}'
    out = render_json_submission(KAB_LINES, existing)
    assert list(json.loads(out)) == ["or", "and"]
    assert json.loads(out) == {"or": "d", "and": "naɣ"}


def test_a_submission_that_is_already_json_passes_through() -> None:
    out = render_json_submission('{"and":"d","or":"naɣ"}', WORD_CONNECTORS_EN)
    assert json.loads(out) == {"and": "d", "or": "naɣ"}


def test_non_ascii_is_not_escaped() -> None:
    assert "naɣ" in render_json_submission(KAB_LINES, WORD_CONNECTORS_EN)


def test_a_list_valued_key_keeps_its_list() -> None:
    existing = '{"yes": ["yes", "yeah"], "no": ["no"]}'
    out = render_json_submission("ih\nuhu\n", existing)
    assert json.loads(out) == {"yes": ["ih"], "no": ["uhu"]}


def test_a_line_count_that_does_not_match_the_keys_is_refused() -> None:
    with pytest.raises(JsonResourceError) as exc:
        render_json_submission("a\nb\nc\n", WORD_CONNECTORS_EN)
    assert "3 line(s)" in str(exc.value) and "2 key(s)" in str(exc.value)


def test_lines_with_no_existing_file_are_refused() -> None:
    """Nothing invents a key: with no file there is no order to fill."""
    with pytest.raises(JsonResourceError) as exc:
        render_json_submission(KAB_LINES, None)
    assert "no file in the target repository" in str(exc.value)


def test_an_existing_file_that_is_not_json_is_refused() -> None:
    with pytest.raises(JsonResourceError) as exc:
        render_json_submission(KAB_LINES, "d\nnaɣ\n")
    assert "not JSON either" in str(exc.value)


def test_a_json_array_is_refused() -> None:
    with pytest.raises(JsonResourceError) as exc:
        render_json_submission("[1, 2]", WORD_CONNECTORS_EN)
    assert "a list of values" in str(exc.value)


def test_an_empty_submission_is_refused() -> None:
    with pytest.raises(JsonResourceError):
        render_json_submission("   \n", WORD_CONNECTORS_EN)


def test_the_validator_leaves_a_json_path_to_the_write_step(capsys) -> None:
    """The gate the workflow runs before the target repo is checked out.

    It cannot decide a JSON submission: the keys a line-per-value submission
    fills live in the file in the target repository, which is not present yet.
    It must not refuse the rescuable case, so it passes and the write step
    renders or refuses. This test pins that, so a later parse-error gate here
    does not silently take the decision back.
    """
    assert validate_submission(KAB_LINES,
                               "ovos_workshop/locale/kab/word_connectors.json") == 0


def test_the_validator_passes_a_json_submission() -> None:
    code = validate_submission('{"and": "d", "or": "na\u0263"}\n',
                               "ovos_workshop/locale/kab/word_connectors.json")
    assert code == 0


def test_a_line_resource_is_unaffected() -> None:
    assert validate_submission(KAB_LINES, "ovos_workshop/locale/kab/and.voc") == 0
def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def test_the_target_file_is_the_first_choice(tmp_path: Path) -> None:
    root = _tree(tmp_path, {
        "locale/kab/word_connectors.json": '{"and": "old", "or": "old"}',
        "locale/en-US/word_connectors.json": WORD_CONNECTORS_EN,
    })
    target = root / "locale/kab/word_connectors.json"
    assert find_key_source(target) == target


def test_a_new_language_takes_the_keys_from_english(tmp_path: Path) -> None:
    """The ovos-workshop#659 shape: kab had no file, en-US had the keys."""
    root = _tree(tmp_path, {
        "locale/en-US/word_connectors.json": WORD_CONNECTORS_EN,
        "locale/pt-PT/word_connectors.json": '{"and": "e", "or": "ou"}',
    })
    (root / "locale/kab").mkdir(parents=True, exist_ok=True)
    found = find_key_source(root / "locale/kab/word_connectors.json")
    assert found == root / "locale/en-US/word_connectors.json"


def test_any_sibling_serves_when_there_is_no_english(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"locale/pt-PT/word_connectors.json": '{"and": "e", "or": "ou"}'})
    (root / "locale/kab").mkdir(parents=True, exist_ok=True)
    found = find_key_source(root / "locale/kab/word_connectors.json")
    assert found == root / "locale/pt-PT/word_connectors.json"


def test_a_sibling_that_is_not_an_object_is_not_a_key_source(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"locale/pt-PT/word_connectors.json": "e\nou\n"})
    (root / "locale/kab").mkdir(parents=True, exist_ok=True)
    assert find_key_source(root / "locale/kab/word_connectors.json") is None


def test_no_sibling_at_all_is_no_key_source(tmp_path: Path) -> None:
    root = _tree(tmp_path, {"locale/kab/other.json": "{}"})
    assert find_key_source(root / "locale/kab/word_connectors.json") is None


def test_the_named_file_of_the_sibling_is_the_one_read(tmp_path: Path) -> None:
    """A sibling with a different resource is not a key source for this one."""
    root = _tree(tmp_path, {"locale/en-US/colors.json": '{"red": "red"}'})
    (root / "locale/kab").mkdir(parents=True, exist_ok=True)
    assert find_key_source(root / "locale/kab/word_connectors.json") is None
    found = find_key_source(root / "locale/kab/colors.json")
    assert found == root / "locale/en-US/colors.json"
    assert json.loads(found.read_text()) == {"red": "red"}

# --- review fixes on #618 ----------------------------------------------------


def test_a_bare_null_is_refused_and_never_written_as_text() -> None:
    """json.loads("null") is None, which was also the "did not parse" marker.

    So a submission of `null` fell through to the line-per-value branch and was
    written as the string "null", where `2` and `true` were refused. The
    sentinel is now an object of its own.
    """
    with pytest.raises(JsonResourceError) as exc:
        render_json_submission("null", '{"zero": "0"}')
    assert "empty" in str(exc.value)


@pytest.mark.parametrize("scalar", ["2", "true", "false", "3.5", '"a string"'])
def test_every_json_scalar_is_refused_the_same_way(scalar) -> None:
    """`null` now answers like the others, rather than being the odd one."""
    with pytest.raises(JsonResourceError):
        render_json_submission(scalar, '{"zero": "0"}')


def test_the_refusal_names_no_python_type() -> None:
    """The text reaches a translator through the issue comment."""
    for submission in ("2", "true", "[1, 2]", "null"):
        try:
            render_json_submission(submission, WORD_CONNECTORS_EN)
        except JsonResourceError as exc:
            message = str(exc)
        else:
            raise AssertionError(f"{submission!r} was not refused")
        # The old text read "not a int", "not a bool", "not a list". The
        # word "list" may still appear in a plain phrase such as "a list of
        # values"; what must not appear is the Python spelling.
        for python_name in ("int", "bool", "list", "NoneType", "float", "str",
                            "dict", "OrderedDict"):
            assert f"not a {python_name}" not in message, (submission, message)
        assert "NoneType" not in message, (submission, message)


def test_an_object_still_passes_through_after_the_sentinel_change() -> None:
    out = render_json_submission('{"and": "d", "or": "na\u0263"}', WORD_CONNECTORS_EN)
    assert json.loads(out) == {"and": "d", "or": "na\u0263"}


def test_a_line_submission_still_renders_after_the_sentinel_change() -> None:
    assert json.loads(render_json_submission(KAB_LINES, WORD_CONNECTORS_EN)) == {
        "and": "d", "or": "na\u0263"}
