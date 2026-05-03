"""Tests for the no-store cache middleware on /api/* responses."""

from uuid import uuid4


def test_api_responses_have_no_store(client):
    """Any /api/* response must carry Cache-Control: no-store, even errors."""
    # Unknown route under /api/ -> 404, but must still get the header so a
    # transient error never gets heuristically cached by the browser.
    response = client.get("/api/this-route-does-not-exist")
    assert response.status_code == 404
    assert response.headers.get("Cache-Control") == "no-store"


def test_non_api_responses_unaffected(client):
    """Routes outside /api/ are not touched by the middleware."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") != "no-store"


def test_og_endpoints_keep_their_cache_header(client):
    """OG routes set their own Cache-Control: the middleware must not clobber it.

    The /api/og/race/{id}/meta route returns a fallback HTML page (still 200)
    with Cache-Control: public, max-age=60 even when the race doesn't exist,
    which is enough to lock in the carve-out without DB fixtures.
    """
    response = client.get(f"/api/og/race/{uuid4()}/meta")
    assert response.status_code == 200
    cache_control = response.headers.get("Cache-Control", "")
    assert "no-store" not in cache_control
    assert "max-age=60" in cache_control
