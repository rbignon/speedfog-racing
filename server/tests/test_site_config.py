"""Test site config endpoint."""

from unittest.mock import patch


def test_site_config_returns_false(client):
    """Returns coming_soon=false when disabled."""
    with patch("speedfog_racing.api.site.settings") as mock_settings:
        mock_settings.coming_soon = False
        response = client.get("/api/site-config")
        assert response.status_code == 200
        assert response.json() == {"coming_soon": False}


def test_site_config_returns_true(client):
    """Returns coming_soon=true when enabled."""
    with patch("speedfog_racing.api.site.settings") as mock_settings:
        mock_settings.coming_soon = True
        response = client.get("/api/site-config")
        assert response.status_code == 200
        assert response.json() == {"coming_soon": True}
