"""Test health endpoint."""


def test_health_check(client):
    """Test that health endpoint returns OK."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_announcement_absent(client, monkeypatch):
    """No announcement configured: both keys are still present, as null."""
    from speedfog_racing.config import settings

    monkeypatch.setattr(settings, "announcement", None)
    monkeypatch.setattr(settings, "announcement_url", None)
    data = client.get("/health").json()
    assert data["announcement"] is None
    assert data["announcement_url"] is None


def test_health_announcement_from_settings(client, monkeypatch):
    """A configured announcement (text + optional link) is exposed to the web UI."""
    from speedfog_racing.config import settings

    monkeypatch.setattr(settings, "announcement", "Mods may break on Friday.")
    monkeypatch.setattr(settings, "announcement_url", "/help#faq-game-update")
    data = client.get("/health").json()
    assert data["announcement"] == "Mods may break on Friday."
    assert data["announcement_url"] == "/help#faq-game-update"
