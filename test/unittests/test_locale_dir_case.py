"""The new-locale directory case the editor writes, run as real JavaScript.

``index.html`` decides the directory name for a locale a skill does not have
yet. The fleet does not spell those names one way: most tracked repositories
use the mixed-case tag (``locale/de-DE/``), a few use lowercase
(``locale/de-de/``), and a handful hold both. A global rule is wrong for one
group whichever way it is written, so ``localeDirFor`` reads the case from the
skill's own sibling locale directories.

The functions are extracted from the page and run under node, so these tests
bind to the shipped code and not to a copy of it.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[2] / "index.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is needed to run the page's JavaScript")


def _js_source() -> str:
    """The two locale-case functions, lifted from the page verbatim."""
    html = INDEX.read_text(encoding="utf-8")
    out = []
    for name in ("siblingLocaleDirs", "localeDirFor"):
        match = re.search(rf"\n    function {name}\(.*?\n    \}}\n", html, re.S)
        assert match, f"index.html no longer declares {name}"
        out.append(match.group(0))
    return "".join(out)


def locale_dir_for(skill: dict, lang: str) -> str:
    """Run the page's ``localeDirFor`` on ``skill`` under node."""
    script = (f"{_js_source()}\n"
              f"process.stdout.write(localeDirFor({json.dumps(skill)}, "
              f"{json.dumps(lang)}));")
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         timeout=60)
    assert run.returncode == 0, run.stderr
    return run.stdout


def _skill(*paths: str) -> dict:
    """A skill whose files sit at ``paths``, in the shape the page reads."""
    files = {}
    for i, path in enumerate(paths):
        lang = re.search(r"(?:^|/)(?:locale|res)/([^/]+)/", path).group(1)
        files[f"f{i}"] = {"langs": {lang: {"file_path": path}}}
    return {"files": files}


ALERTS = _skill(
    "locale/ca-ES/dialog/alarm.dialog",
    "locale/da-DK/dialog/alarm.dialog",
    "locale/de-DE/dialog/alarm.dialog",
    "locale/en-US/dialog/alarm.dialog",
)
LOWERCASE = _skill(
    "locale/ca-es/dialog/hass.dialog",
    "locale/da-dk/dialog/hass.dialog",
    "locale/en-us/dialog/hass.dialog",
)


def test_alerts_style_tree_keeps_the_mixed_case_tag() -> None:
    """A repository whose locales are ca-ES, da-DK, de-DE gets pt-PT."""
    assert locale_dir_for(ALERTS, "pt-PT") == "pt-PT"


def test_lowercase_tree_gets_a_lowercase_directory() -> None:
    """A repository whose locales are ca-es, da-dk, en-us gets pt-pt."""
    assert locale_dir_for(LOWERCASE, "pt-PT") == "pt-pt"


def test_a_repository_holding_both_cases_takes_the_mixed_case_tag() -> None:
    """Mixed-case is the fleet convention, so one such sibling decides it."""
    both = _skill("locale/en-US/dialog/a.dialog", "locale/en-us/dialog/a.dialog")
    assert locale_dir_for(both, "pt-PT") == "pt-PT"


def test_no_locale_directory_falls_back_to_lowercase() -> None:
    """With nothing to read, the page keeps the lowercase it wrote before."""
    assert locale_dir_for({"files": {}}, "pt-PT") == "pt-pt"


def test_a_region_less_sibling_does_not_vote_for_lowercase() -> None:
    """``locale/pt/`` is lowercase either way, so it must not decide the case.

    Counting it would send every new locale in an ``en``/``pt`` repository to
    lowercase on evidence that says nothing about the convention.
    """
    region_less = _skill("locale/pt/dialog/a.dialog", "locale/en-US/dialog/a.dialog")
    assert locale_dir_for(region_less, "de-DE") == "de-DE"


def test_res_trees_are_read_too() -> None:
    """An older skill keeps its locales under ``res/``, not ``locale/``."""
    res = _skill("res/de-DE/dialog/a.dialog", "res/en-US/dialog/a.dialog")
    assert locale_dir_for(res, "pt-PT") == "pt-PT"
