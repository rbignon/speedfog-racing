"""Tests for the public GET /api/rewards/catalog endpoint.

Tests that just re-assert literal catalog values through the API were
removed: they mirror the source of truth and break on any catalog edit
without catching real bugs. The smoke test plus the wire-format invariants
below cover the contract that's actually testable here.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient

from speedfog_racing.main import app


def test_catalog_returns_top_level_shape():
    """Smoke: endpoint reachable and returns the three expected sections."""
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {"badges", "name_templates", "phantom_skins"}
        assert isinstance(data["badges"], list)
        assert isinstance(data["name_templates"], list)
        assert isinstance(data["phantom_skins"], list)


def test_catalog_phantom_skins_sorted_by_sort_order():
    """Wire-format invariant: phantom skins are returned sorted."""
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        skins = resp.json()["phantom_skins"]
        orders = [s["sort_order"] for s in skins]
        assert orders == sorted(orders)
