"""Tests for the public GET /api/rewards/catalog endpoint."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient

from speedfog_racing.main import app


def test_catalog_returns_badges_and_templates():
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "badges" in data and "name_templates" in data
        badge_ids = {b["id"] for b in data["badges"]}
        assert {"early_adopter", "contributor", "top1_elo", "weekly_daily_champion"} <= badge_ids
        template_ids = {t["id"] for t in data["name_templates"]}
        assert {"default", "elo_crown", "runebearer"} <= template_ids


def test_catalog_template_carries_color_or_gradient():
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        data = resp.json()
        default = next(t for t in data["name_templates"] if t["id"] == "default")
        assert default["color"] == "#FFFFFF"
        assert default["gradient"] is None
        assert default["name_css"] is None
        crown = next(t for t in data["name_templates"] if t["id"] == "elo_crown")
        assert crown["gradient"] == ["#FFE9A8", "#C8A44E"]
        assert crown["background_css"] is not None
        assert crown["name_css"] is not None
        assert "Georgia" in crown["name_css"]
        assert "italic" in crown["name_css"]


def test_catalog_runebearer_template():
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        data = resp.json()
        rune = next(t for t in data["name_templates"] if t["id"] == "runebearer")
        assert rune["gradient"] == ["#B8C5D6", "#6F87A6"]
        assert rune["name_css"] is not None
        assert "italic" in rune["name_css"]
        assert rune["background_css"] is not None


def test_catalog_badge_carries_lifecycle_and_icon():
    with TestClient(app) as client:
        resp = client.get("/api/rewards/catalog")
        data = resp.json()
        ea = next(b for b in data["badges"] if b["id"] == "early_adopter")
        assert ea["lifecycle"] == "permanent"
        assert ea["icon_filename"] == "early_adopter.svg"
        top1 = next(b for b in data["badges"] if b["id"] == "top1_elo")
        assert top1["lifecycle"] == "transient"
