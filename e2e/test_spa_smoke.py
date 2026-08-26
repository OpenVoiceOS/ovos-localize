"""SPA smoke tests (B3.0).

These pin the behaviours a weak future change is most likely to break: the app
shell, hash-route navigation, and the accessibility landmarks. They run against
the real single-file SPA with no data fixtures (its data fetches degrade
gracefully), so they are fast and deterministic.
"""


def test_shell_renders(page, base_url):
    page.goto(base_url + "/")
    assert page.locator("header").is_visible()
    assert page.locator("header nav").count() == 1
    assert page.locator("main#app").count() == 1
    assert page.locator("footer").is_visible()


def test_landing_renders(page, base_url):
    page.goto(base_url + "/")
    page.wait_for_selector("h1")
    assert "translate" in page.locator("h1").first.inner_text().lower()


def test_hash_route_navigation(page, base_url):
    """The router, not the browser, must be what changes the view.

    Clicking an anchor sets location.hash on its own, and the landing
    heading stays on screen if nothing re-renders, so asserting on the hash
    or on "a heading exists" passes even with the router deleted. Assert the
    rendered content actually changed instead.
    """
    page.goto(base_url + "/")
    page.wait_for_selector("main#app h1, main#app h2")
    before = page.locator("main#app h1, main#app h2").first.inner_text()

    page.locator("header nav").get_by_role("link", name="How it works").click()
    page.wait_for_function("location.hash === '#/how-it-works'")
    page.wait_for_function(
        "(prev) => {"
        "  const h = document.querySelector('main#app h1, main#app h2');"
        "  return h && h.innerText.trim() !== prev;"
        "}",
        arg=before.strip(),
    )
    after = page.locator("main#app h1, main#app h2").first.inner_text()
    assert after.strip() != before.strip()


def test_nav_has_all_primary_links(page, base_url):
    page.goto(base_url + "/")
    nav = page.locator("header nav")
    for label in ["Dashboard", "Stats", "Open Data", "How it works"]:
        assert nav.get_by_text(label, exact=True).count() >= 1


def test_document_title_follows_the_route(page, base_url):
    """Each view sets its own title.

    A hash router leaves the tab title on whatever loaded first, so a
    translator with several views open cannot tell them apart, and a crawler
    that runs the script sees one title for the whole site.
    """
    page.goto(base_url + "/")
    page.wait_for_function("document.title.length > 0")
    landing = page.title()

    page.locator("header nav").get_by_role("link", name="Stats").click()
    page.wait_for_function("location.hash === '#/stats'")
    page.wait_for_function("(prev) => document.title !== prev", arg=landing)
    assert page.title() != landing
    assert "OVOS Localize" in page.title()
