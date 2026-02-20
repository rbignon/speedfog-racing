"""Test configuration and fixtures."""

import json
import os
from pathlib import Path

# Set test environment variables BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.rate_limit import limiter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Sync engine for test setup (SQLite)
SYNC_DATABASE_URL = "sqlite:///./test.db"

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def override_get_db():
    """Override database dependency for tests."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def sample_graph_json() -> dict:
    """Load a real v3 graph.json shipped as a test fixture."""
    path = FIXTURES_DIR / "sample_graph.json"
    return json.loads(path.read_text())


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create test database tables once per session."""
    Base.metadata.create_all(bind=sync_engine)
    yield
    Base.metadata.drop_all(bind=sync_engine)
    # Clean up test.db file
    if os.path.exists("./test.db"):
        os.remove("./test.db")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset rate limiter state between tests to avoid cross-test pollution."""
    limiter.reset()
    yield


@pytest.fixture(scope="function")
def client():
    """Create test client."""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
