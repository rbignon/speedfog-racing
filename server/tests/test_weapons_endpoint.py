"""Smoke tests for the public weapons catalogue endpoint."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from starlette.testclient import TestClient

from speedfog_racing.main import app


def test_catalogue_endpoint_returns_non_empty_dict() -> None:
    with TestClient(app) as client:
        response = client.get("/api/weapons")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    assert len(body) > 400
    longsword = body.get("2000000")
    assert longsword == {"name": "Longsword", "wep_type": 3}


def test_catalogue_endpoint_serves_cache_control_header() -> None:
    with TestClient(app) as client:
        response = client.get("/api/weapons")
    assert response.status_code == 200
    cache_control = response.headers.get("cache-control", "")
    assert "max-age" in cache_control


def test_catalogue_endpoint_accepts_anonymous_requests() -> None:
    # Optional auth: an anonymous GET must succeed for V1.
    with TestClient(app) as client:
        response = client.get("/api/weapons")
    assert response.status_code == 200
