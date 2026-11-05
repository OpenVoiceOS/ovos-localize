"""The page finds English in any region, en-US first.

A bare ``locale/en`` tree is filed as en-GB, its default region. chronologia
and simple_NER ship English only that way. The skill page and the editor
must still read those skills against their English, not against a first
language picked by key order or against an en-US that does not exist.

The manifest is served through a route, so the test does not depend on the
data the daily scan commits.
"""

import json

import pytest

SKILL = "chronologia"


def _lang(path, lines):
    return {
        "entries": [{"line": i + 1, "text": t} for i, t in enumerate(lines)],
        "line_count": len(lines),
        "slots": [],
        "validation": [],
        "file_path": path,
    }


def _file(langs):
    return {"type": "voc", "intent_system": "none", "langs": langs, "context": {}, "edit_urls": {}}


# Key order matters: ast and an come before en-GB, as in the scanned
# chronologia manifest, so a first-key fallback picks a non-English source.
FILES = {
    "era_ad_suffix.voc": _file({
        "ast": _lang("chronologia/locale/ast/era_ad_suffix.voc", ["después de cristu"]),
        "de-DE": _lang("chronologia/locale/de/era_ad_suffix.voc", ["nach christus", "n. chr.", "n.chr."]),
        "en-GB": _lang("chronologia/locale/en/era_ad_suffix.voc",
                       ["anno domini", "common era", "a.d.", "c.e.", "ad", "ce"]),
    }),
    "era_bc_suffix.voc": _file({
        "an": _lang("chronologia/locale/an/era_bc_suffix.voc", ["antes de cristo"]),
        "en-GB": _lang("chronologia/locale/en/era_bc_suffix.voc", ["before christ", "b.c.", "bc", "bce"]),
        "de-DE": _lang("chronologia/locale/de/era_bc_suffix.voc", ["vor christus", "v. chr."]),
    }),
    "season_autumn.voc": _file({
        "ast": _lang("chronologia/locale/ast/season_autumn.voc", ["seronda"]),
        "en-GB": _lang("chronologia/locale/en/season_autumn.voc", ["autumn", "fall"]),
    }),
}

MANIFEST = {
    "id": SKILL,
    "repo": "TigreGotico/chronologia",
    "skill_class": "",
    "source_file": "",
    "languages": ["an", "ast", "de-DE", "en-GB"],
    "bad_lang_codes": ["an", "ast", "de", "en"],
    "locale_dir": "chronologia/locale",
    "branch": "dev",
    "commit": "0" * 40,
    "entry_points": [],
    "skill_id": None,
    "golden": [],
    "files": FILES,
}


@pytest.fixture()
def chronologia_page(page):
    page.route(
        f"**/data/skills/{SKILL}.json",
        lambda route: route.fulfill(content_type="application/json", body=json.dumps(MANIFEST)),
    )
    return page


def test_editor_reads_against_english_in_any_region(chronologia_page, base_url):
    chronologia_page.goto(f"{base_url}/#/skill/{SKILL}/era_ad_suffix.voc/de-DE")
    select = chronologia_page.locator("#src-lang-select")
    select.wait_for()
    assert select.input_value() == "en-GB"


def test_skill_page_counts_against_the_source_language(chronologia_page, base_url):
    # Independent of the page: count the fixture's files by hand.
    source_files = sum("en-GB" in f["langs"] for f in FILES.values())
    translated = sum("de-DE" in f["langs"] for f in FILES.values())
    assert (source_files, translated) == (3, 2)

    chronologia_page.goto(f"{base_url}/#/skill/{SKILL}/de-DE")
    chronologia_page.get_by_text("files translated").wait_for()
    stats = chronologia_page.locator("main#app .grid.grid-cols-4 > div")
    values = [stats.nth(i).locator("div").first.inner_text().strip() for i in range(3)]
    assert values == [f"{translated}/{source_files}", f"{translated / source_files * 100:.0f}%",
                      str(source_files - translated)]

    row = chronologia_page.locator("main#app a", has_text="era_ad_suffix.voc")
    assert "en-GB: 6" in row.inner_text()
