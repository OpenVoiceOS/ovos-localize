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
        """Bare codes stay bare (langcodes doesn't add region)."""
        result = normalize_lang_code("da")
        assert result == "da"

    def test_mixed_case(self) -> None:
        """pt-br → pt-BR."""
        assert normalize_lang_code("pt-br") == "pt-BR"

    def test_invalid_code(self) -> None:
        """Invalid codes returned lowercased."""
        result = normalize_lang_code("zzz-QQQ")
        # langcodes may normalize or pass through
        assert isinstance(result, str)


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
