"""Test health endpoint."""


def test_health_check(client):
    """Test that health endpoint returns OK."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_announcement_absent(client, monkeypatch):
    """No announcement configured: the keys are still present, as null."""
    from speedfog_racing.config import settings

    monkeypatch.setattr(settings, "announcement", None)
    monkeypatch.setattr(settings, "announcement_url", None)
    monkeypatch.setattr(settings, "announcement_link_text", None)
    data = client.get("/health").json()
    assert data["announcement"] is None
    assert data["announcement_url"] is None
    assert data["announcement_link_text"] is None


def test_health_announcement_from_settings(client, monkeypatch):
    """A configured announcement (text + optional link and its label) is exposed
    to the web UI."""
    from speedfog_racing.config import settings

    monkeypatch.setattr(settings, "announcement", "Mods may break on Friday.")
    monkeypatch.setattr(settings, "announcement_url", "/help#faq-game-update")
    monkeypatch.setattr(settings, "announcement_link_text", "What to do")
    data = client.get("/health").json()
    assert data["announcement"] == "Mods may break on Friday."
    assert data["announcement_url"] == "/help#faq-game-update"
    assert data["announcement_link_text"] == "What to do"


def test_health_is_never_rate_limited(client):
    """Every page load and tab focus polls /health, and behind a proxy that does
    not forward the client IP a per-IP limit is one bucket for every visitor."""
    statuses = {client.get("/health").status_code for _ in range(70)}
    assert statuses == {200}


def test_api_routes_keep_the_default_rate_limit(client):
    """Control: the default 60/minute limit still applies to the API."""
    statuses = [client.get("/api/rewards/catalog").status_code for _ in range(61)]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
