"""Tests for the i18n translation service."""

from pathlib import Path

import pytest

from speedfog_racing.services.i18n import (
    TranslationData,
    _apply_french_contractions,
    _format_display_name,
    _translate_name,
    _translate_text,
    load_translations,
    translate_graph_json,
    translate_zone_update,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fr_data() -> TranslationData:
    """Load real French translations from the data directory."""
    i18n_dir = Path(__file__).resolve().parent.parent / "data" / "i18n"
    translations = load_translations(i18n_dir)
    assert "fr" in translations, "French translation file not found"
    return translations["fr"]


# ---------------------------------------------------------------------------
# Name translation
# ---------------------------------------------------------------------------


class TestTranslateName:
    def test_boss_name(self, fr_data: TranslationData) -> None:
        assert _translate_name("Malenia", fr_data) == "Malenia"
        assert _translate_name("Fire Giant", fr_data) == "le Géant de feu"

    def test_region_name(self, fr_data: TranslationData) -> None:
        assert _translate_name("Limgrave", fr_data) == "Nécrolimbe"
        assert _translate_name("Altus Plateau", fr_data) == "le Plateau Altus"

    def test_location_name(self, fr_data: TranslationData) -> None:
        assert _translate_name("Raya Lucaria", fr_data) == "Raya Lucaria"
        assert _translate_name("Stormveil Castle", fr_data) == "le Château de Voilorage"

    def test_unknown_name_returns_original(self, fr_data: TranslationData) -> None:
        assert _translate_name("Unknown Place XYZ", fr_data) == "Unknown Place XYZ"

    def test_boss_takes_precedence(self, fr_data: TranslationData) -> None:
        """Bosses are checked first, then regions, then locations."""
        assert _translate_name("Loretta", fr_data) == "Loretta"

    def test_composite_name(self, fr_data: TranslationData) -> None:
        """'Region - Location - Boss' splits and translates each part."""
        result = _translate_name("Capital Outskirts - Sealed Tunnel - Onyx Lord", fr_data)
        assert "Faubourgs" in result
        assert "Galerie scellée" in result
        assert "Seigneur d'onyx" in result

    def test_composite_partial_translation(self, fr_data: TranslationData) -> None:
        """Untranslated parts stay in English."""
        result = _translate_name("Altus Plateau - Sage's Cave", fr_data)
        assert result == "le Plateau Altus - Sage's Cave"


# ---------------------------------------------------------------------------
# French contractions
# ---------------------------------------------------------------------------


class TestFrenchContractions:
    def test_de_le(self) -> None:
        assert _apply_french_contractions("devant l'arène de le Géant de feu") == (
            "devant l'arène du Géant de feu"
        )

    def test_de_les(self) -> None:
        assert _apply_french_contractions("après de les Champions de Fia") == (
            "après des Champions de Fia"
        )

    def test_a_le(self) -> None:
        assert _apply_french_contractions("à le Plateau Altus") == "au Plateau Altus"

    def test_a_les(self) -> None:
        assert _apply_french_contractions("à les Cimes des Géants") == "aux Cimes des Géants"

    def test_no_contraction_needed(self) -> None:
        assert _apply_french_contractions("de la Péninsule") == "de la Péninsule"
        assert _apply_french_contractions("de l'Ainsel") == "de l'Ainsel"


# ---------------------------------------------------------------------------
# Text translation (overrides → patterns → fallback)
# ---------------------------------------------------------------------------


class TestTranslateText:
    def test_override_exact_match(self, fr_data: TranslationData) -> None:
        result = _translate_text("Warp after Maliketh", "text", fr_data)
        assert result == "Téléportation après Maliketh"

    def test_override_side_text(self, fr_data: TranslationData) -> None:
        result = _translate_text(
            "warp after defeathing Maliketh, or repeating the warp using the grace",
            "side_text",
            fr_data,
        )
        assert "Maliketh" in result
        assert "téléportation" in result.lower()

    def test_pattern_boss_front(self, fr_data: TranslationData) -> None:
        result = _translate_text("Margit front", "text", fr_data)
        assert result == "Margit (devant)"

    def test_pattern_boss_back(self, fr_data: TranslationData) -> None:
        result = _translate_text("Malenia back", "text", fr_data)
        assert result == "Malenia (derrière)"

    def test_pattern_zone_entrance(self, fr_data: TranslationData) -> None:
        result = _translate_text("Limgrave entrance", "text", fr_data)
        assert result == "Entrée de Nécrolimbe"

    def test_pattern_side_text_with_boss_possessive(self, fr_data: TranslationData) -> None:
        result = _translate_text("at the front of Margit's arena", "side_text", fr_data)
        assert result == "devant l'arène de Margit"

    def test_pattern_plural_possessive(self, fr_data: TranslationData) -> None:
        """Plural possessive {boss}' (no trailing s) matches the pattern."""
        result = _translate_text("before Cleanrot Knights' arena", "side_text", fr_data)
        assert "Chevaliers de la Noble putréfaction" in result
        assert result.startswith("avant l'arène")

    def test_pattern_with_contraction(self, fr_data: TranslationData) -> None:
        """Pattern substitution followed by French grammar contraction."""
        result = _translate_text("at the front of Fire Giant's arena", "side_text", fr_data)
        # "de le Géant de feu" → "du Géant de feu"
        assert "du Géant de feu" in result

    def test_fallback_unknown_text(self, fr_data: TranslationData) -> None:
        result = _translate_text("Some unknown gate label 12345", "text", fr_data)
        assert result == "Some unknown gate label 12345"

    def test_empty_text(self, fr_data: TranslationData) -> None:
        assert _translate_text("", "text", fr_data) == ""

    def test_pattern_zone_exit(self, fr_data: TranslationData) -> None:
        result = _translate_text("Limgrave exit", "text", fr_data)
        assert result == "Sortie de Nécrolimbe"


# ---------------------------------------------------------------------------
# Display name formatting (article stripping)
# ---------------------------------------------------------------------------


class TestFormatDisplayName:
    def test_strip_le(self) -> None:
        assert _format_display_name("le Géant de feu") == "Géant de feu"

    def test_strip_la(self) -> None:
        assert _format_display_name("la Danseuse de Ranah") == "Danseuse de Ranah"

    def test_strip_les(self) -> None:
        assert (
            _format_display_name("les Veilleurs de l'Arbre-Monde") == "Veilleurs de l'Arbre-Monde"
        )

    def test_strip_l_apostrophe(self) -> None:
        assert _format_display_name("l'Esprit ancestral") == "Esprit ancestral"

    def test_no_article(self) -> None:
        assert _format_display_name("Malenia") == "Malenia"
        assert _format_display_name("Nécrolimbe") == "Nécrolimbe"

    def test_composite_name(self) -> None:
        result = _format_display_name(
            "les Faubourgs de la capitale - la Galerie scellée - le Seigneur d'onyx"
        )
        assert result == "Faubourgs de la capitale - Galerie scellée - Seigneur d'onyx"

    def test_internal_articles_preserved(self) -> None:
        """Only the leading article is stripped; internal 'de la', 'du' stay."""
        assert _format_display_name("le Château de Voilorage") == "Château de Voilorage"


# ---------------------------------------------------------------------------
# Graph JSON translation
# ---------------------------------------------------------------------------


class TestTranslateGraphJson:
    def test_english_returns_same_object(self) -> None:
        graph = {"nodes": {"a": {"display_name": "Test"}}}
        result = translate_graph_json(graph, "en")
        assert result is graph

    def test_unknown_locale_returns_same_object(self) -> None:
        graph = {"nodes": {"a": {"display_name": "Test"}}}
        result = translate_graph_json(graph, "xx")
        assert result is graph

    def test_translates_display_names(self, fr_data: TranslationData) -> None:
        graph = {
            "nodes": {
                "stormveil_123": {
                    "display_name": "Stormveil Castle",
                    "layer": 1,
                    "tier": 3,
                },
                "limgrave_456": {
                    "display_name": "Limgrave",
                    "layer": 0,
                    "tier": 1,
                },
            }
        }
        result = translate_graph_json(graph, "fr")
        assert result is not graph  # Deep copy
        # Articles stripped + capitalized for display context
        assert result["nodes"]["stormveil_123"]["display_name"] == "Château de Voilorage"
        assert result["nodes"]["limgrave_456"]["display_name"] == "Nécrolimbe"

    def test_translates_exit_text(self, fr_data: TranslationData) -> None:
        graph = {
            "nodes": {
                "boss_abc": {
                    "display_name": "Margit",
                    "exits": [
                        {"to": "castle_def", "text": "Margit front"},
                        {"to": "limgrave_ghi", "text": "Margit back"},
                    ],
                }
            }
        }
        result = translate_graph_json(graph, "fr")
        exits = result["nodes"]["boss_abc"]["exits"]
        assert exits[0]["text"] == "Margit (devant)"
        assert exits[1]["text"] == "Margit (derrière)"

    def test_exit_text_falls_back_to_side_text(self, fr_data: TranslationData) -> None:
        """Exit text with side_text content (output.py puts side_text into text field)."""
        graph = {
            "nodes": {
                "boss_abc": {
                    "display_name": "Margit",
                    "exits": [
                        {"to": "x", "text": "at the front of Margit's arena"},
                    ],
                }
            }
        }
        result = translate_graph_json(graph, "fr")
        exit_text = result["nodes"]["boss_abc"]["exits"][0]["text"]
        assert exit_text == "devant l'arène de Margit"

    def test_translates_node_type(self, fr_data: TranslationData) -> None:
        """Node type should get a display_type from [types] section, original type preserved."""
        graph = {
            "nodes": {
                "a": {
                    "display_name": "Limgrave",
                    "type": "legacy_dungeon",
                }
            }
        }
        result = translate_graph_json(graph, "fr")
        # Original type preserved for frontend rendering logic
        assert result["nodes"]["a"]["type"] == "legacy_dungeon"
        # Translated type added as display_type
        assert result["nodes"]["a"]["display_type"] == "donjon majeur"

    def test_original_not_mutated_graph(self, fr_data: TranslationData) -> None:
        graph = {
            "nodes": {
                "a": {
                    "display_name": "Limgrave",
                    "exits": [{"to": "b", "text": "Margit front"}],
                }
            }
        }
        translate_graph_json(graph, "fr")
        assert graph["nodes"]["a"]["display_name"] == "Limgrave"
        assert graph["nodes"]["a"]["exits"][0]["text"] == "Margit front"

    def test_caching(self, fr_data: TranslationData) -> None:
        graph = {"nodes": {"a": {"display_name": "Limgrave"}}}
        result1 = translate_graph_json(graph, "fr")
        result2 = translate_graph_json(graph, "fr")
        # Same object from cache
        assert result1 is result2


# ---------------------------------------------------------------------------
# Zone update translation
# ---------------------------------------------------------------------------


class TestTranslateZoneUpdate:
    def test_english_returns_same_object(self) -> None:
        msg = {"type": "zone_update", "display_name": "Test", "exits": []}
        result = translate_zone_update(msg, "en")
        assert result is msg

    def test_translates_display_name_and_exits(self, fr_data: TranslationData) -> None:
        msg = {
            "type": "zone_update",
            "node_id": "boss_123",
            "display_name": "Fire Giant",
            "exits": [
                {"text": "Fire Giant front left", "to_name": "Limgrave", "discovered": False},
                {
                    "text": "Fire Giant front right",
                    "to_name": "Stormveil Castle",
                    "discovered": True,
                },
            ],
        }
        result = translate_zone_update(msg, "fr")
        assert result is not msg
        # display_name: article stripped + capitalized
        assert result["display_name"] == "Géant de feu"
        # to_name: keeps full article (used in text context)
        assert result["exits"][0]["to_name"] == "Nécrolimbe"
        assert result["exits"][1]["to_name"] == "le Château de Voilorage"
        # Text patterns
        assert "(avant gauche)" in result["exits"][0]["text"]
        assert "(avant droit)" in result["exits"][1]["text"]

    def test_exit_text_falls_back_to_side_text(self, fr_data: TranslationData) -> None:
        """Zone update exits also fall back to side_text patterns."""
        msg = {
            "type": "zone_update",
            "node_id": "boss_123",
            "display_name": "Margit",
            "exits": [
                {
                    "text": "at the front of Margit's arena",
                    "to_name": "Limgrave",
                    "discovered": True,
                },
            ],
        }
        result = translate_zone_update(msg, "fr")
        assert result["exits"][0]["text"] == "devant l'arène de Margit"

    def test_original_not_mutated(self, fr_data: TranslationData) -> None:
        msg = {
            "type": "zone_update",
            "display_name": "Limgrave",
            "exits": [{"text": "Limgrave entrance", "to_name": "Stormveil Castle"}],
        }
        translate_zone_update(msg, "fr")
        assert msg["display_name"] == "Limgrave"
        assert msg["exits"][0]["text"] == "Limgrave entrance"


# ---------------------------------------------------------------------------
# get_available_locales
# ---------------------------------------------------------------------------


class TestGetAvailableLocales:
    def test_includes_english(self, fr_data: TranslationData) -> None:
        from speedfog_racing.services.i18n import get_available_locales

        locales = get_available_locales()
        codes = [loc["code"] for loc in locales]
        assert "en" in codes
        assert "fr" in codes

    def test_english_always_first(self, fr_data: TranslationData) -> None:
        from speedfog_racing.services.i18n import get_available_locales

        locales = get_available_locales()
        assert locales[0]["code"] == "en"
        assert locales[0]["name"] == "English"
