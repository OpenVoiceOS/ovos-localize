"""Unit tests for language utilities."""

from ovos_localize.lang_utils import (
    normalize_lang_code,
    merge_equivalent_langs,
    lang_display_name,
    lang_display_name_native,
)


class TestNormalizeLangCode:
    """Tests for normalize_lang_code()."""

    def test_lowercase_to_bcp47(self) -> None:
        """en-us → en-US."""
        assert normalize_lang_code("en-us") == "en-US"

    def test_already_normalized(self) -> None:
        """en-US stays en-US."""
        assert normalize_lang_code("en-US") == "en-US"

    def test_bare_code(self) -> None:
        """Bare codes are expanded to full BCP-47 via EXPLICIT_MAPPING."""
        assert normalize_lang_code("da") == "da-DK"
        assert normalize_lang_code("en") == "en-US"
        assert normalize_lang_code("pt") == "pt-BR"

    def test_mixed_case(self) -> None:
        """pt-br → pt-BR."""
        assert normalize_lang_code("pt-br") == "pt-BR"

    def test_invalid_code(self) -> None:
        """Invalid codes returned lowercased."""
        result = normalize_lang_code("zzz-QQQ")
        # langcodes may normalize or pass through
        assert isinstance(result, str)

    def test_explicit_mapping(self) -> None:
        """Verify explicit OVOS mappings."""
        assert normalize_lang_code("ca") == "ca-ES"
        assert normalize_lang_code("de") == "de-DE"
        assert normalize_lang_code("es") == "es-ES"
        assert normalize_lang_code("fa-FA") == "fa-IR"
        assert normalize_lang_code("fr") == "fr-FR"
        assert normalize_lang_code("gl") == "gl-ES"
        assert normalize_lang_code("it") == "it-IT"
        assert normalize_lang_code("nl") == "nl-NL"
        assert normalize_lang_code("pt") == "pt-BR"
        assert normalize_lang_code("eu") == "eu-ES"
        assert normalize_lang_code("eu-EU") == "eu-ES"
        assert normalize_lang_code("es-LM") == "es-419"
        # Case insensitive
        assert normalize_lang_code("CA") == "ca-ES"
        assert normalize_lang_code("EU-eu") == "eu-ES"

    def test_kabyle_stays_bare(self) -> None:
        """Kabyle (kab) has no commonly-used region subtag — normalization
        MUST NOT invent one (e.g. kab-DZ); it stays the bare macrolanguage
        code, same as it would appear in a locale directory name."""
        assert normalize_lang_code("kab") == "kab"
        assert normalize_lang_code("KAB") == "kab"


class TestMergeEquivalentLangs:
    """Tests for merge_equivalent_langs()."""

    def test_bare_merges_into_full(self) -> None:
        """da merges into da-DK (distance 0)."""
        result = merge_equivalent_langs(["da", "da-DK"])
        assert result["da"] == "da-DK"
        assert result["da-DK"] == "da-DK"

    def test_distinct_stay_separate(self) -> None:
        """pt-BR and pt-PT stay separate."""
        result = merge_equivalent_langs(["pt-BR", "pt-PT"])
        assert result["pt-BR"] == "pt-BR"
        assert result["pt-PT"] == "pt-PT"

    def test_no_merge_needed(self) -> None:
        """All distinct codes map to themselves."""
        result = merge_equivalent_langs(["en-US", "de-DE", "fr-FR"])
        assert all(result[k] == k for k in result)

    def test_empty(self) -> None:
        """Empty input returns empty dict."""
        assert merge_equivalent_langs([]) == {}


class TestLangDisplayName:
    """Tests for display name functions."""

    def test_display_name(self) -> None:
        """Returns human-readable name."""
        name = lang_display_name("pt-BR")
        assert "Portuguese" in name or "português" in name.lower()

    def test_display_name_native(self) -> None:
        """Returns native name."""
        name = lang_display_name_native("de-DE")
        assert "Deutsch" in name

    def test_unknown_code(self) -> None:
        """Unknown code returns the code itself."""
        name = lang_display_name("zzz")
        assert isinstance(name, str)

    def test_native_unknown(self) -> None:
        """Unknown code for native returns the code."""
        name = lang_display_name_native("zzz")
        assert isinstance(name, str)


class TestCanonicalCodeWins:
    """A deliberately enabled code must not lose to a stray region tag.

    Kabyle is ``kab``; there is no commonly-used ``kab-DZ``.  One stray
    ``kab-DZ`` locale directory in the scanned corpus was enough to make the
    platform serve Kabyle as ``kab-DZ`` and file every translation under it.
    """

    def test_enabled_bare_code_beats_invented_region(self) -> None:
        merged = merge_equivalent_langs(["kab", "kab-DZ"], canonical_codes=["kab"])
        assert merged["kab"] == "kab"
        assert merged["kab-DZ"] == "kab"

    def test_without_enabled_list_specific_still_wins(self) -> None:
        """Unchanged behaviour when nothing is declared canonical."""
        merged = merge_equivalent_langs(["da", "da-DK"])
        assert merged["da"] == "da-DK"

    def test_enabled_regional_code_still_wins(self) -> None:
        merged = merge_equivalent_langs(["da", "da-DK"], canonical_codes=["da-DK"])
        assert merged["da"] == "da-DK"
        assert merged["da-DK"] == "da-DK"

    def test_distant_tags_never_merge(self) -> None:
        """sv-FI and sv-SE are different languages to a translator."""
        merged = merge_equivalent_langs(["sv-FI", "sv-SE"], canonical_codes=["sv-SE"])
        assert merged["sv-FI"] == "sv-FI"
        assert merged["sv-SE"] == "sv-SE"

    def test_other_bare_enabled_codes_protected(self) -> None:
        """an and ast are region-less in enabled_languages.txt too."""
        codes = ["an", "an-ES", "ast", "ast-ES"]
        merged = merge_equivalent_langs(codes, canonical_codes=["an", "ast"])
        assert merged["an-ES"] == "an"
        assert merged["ast-ES"] == "ast"

    def test_mirandese_region_is_not_equivalent(self) -> None:
        """``mwl`` and ``mwl-PT`` are distance 4, so they never merge -- the
        enabled-code preference must not force unrelated tags together."""
        merged = merge_equivalent_langs(["mwl", "mwl-PT"], canonical_codes=["mwl"])
        assert merged["mwl"] == "mwl"
        assert merged["mwl-PT"] == "mwl-PT"
    def test_kabyle_display_name(self) -> None:
        """langcodes resolves kab without an explicit override — verify the
        installed langcodes/language_data actually has Kabyle coverage
        rather than trusting it blindly."""
        name = lang_display_name("kab")
        assert name != "kab"
        assert "Kabyle" in name

    def test_kabyle_native_name(self) -> None:
        name = lang_display_name_native("kab")
        assert name != "kab"
        assert "Taqbaylit" in name
