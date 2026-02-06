"""Unit tests for layer service."""

from speedfog_racing.services.layer_service import get_layer_for_zone


def test_get_layer_for_known_zone():
    graph = {"area_tiers": {"Limgrave": 1, "Liurnia": 2, "Caelid": 3}}
    assert get_layer_for_zone("Limgrave", graph) == 1
    assert get_layer_for_zone("Liurnia", graph) == 2
    assert get_layer_for_zone("Caelid", graph) == 3


def test_get_layer_for_unknown_zone():
    graph = {"area_tiers": {"Limgrave": 1}}
    assert get_layer_for_zone("UnknownArea", graph) == 0


def test_get_layer_with_no_area_tiers():
    graph = {"total_layers": 5, "nodes": []}
    assert get_layer_for_zone("Limgrave", graph) == 0


def test_get_layer_with_empty_area_tiers():
    graph = {"area_tiers": {}}
    assert get_layer_for_zone("Limgrave", graph) == 0
