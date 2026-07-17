"""Test configuration and fixtures."""

import json
import os
from pathlib import Path

# Set test environment variables BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.setdefault("COUNTDOWN_SECONDS", "0")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Pool
from speedfog_racing.rate_limit import limiter


# Auto-seed a default ``standard`` Pool row whenever the ``pools`` table is
# created. This keeps the FK + ``Pool.enabled`` guard in ``create_race`` and
# ``create_session`` happy in the dozens of test files that spin up their own
# in-memory SQLite engine via ``Base.metadata.create_all`` without each of
# them having to repeat the seeding boilerplate. Individual tests can still
# add more Pool rows as needed.
@event.listens_for(Pool.__table__, "after_create")
def _seed_default_pool(target, connection, **kw):  # type: ignore[no-untyped-def]
    connection.execute(
        target.insert().values(
            name="standard",
            enabled=True,
            config={"name": "Standard"},
        )
    )


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
    """Create test database tables once per session.

    The ``after_create`` listener above auto-seeds a default ``standard``
    Pool row so that fixtures inserting ``Seed(pool_name="standard", ...)``
    satisfy the FK and the ``create_race`` / ``create_session`` enabled
    guard without extra boilerplate.
    """
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


@pytest.fixture(autouse=True)
def _clear_stats_cache():
    """Clear the public stats TTL cache between tests to avoid cross-test pollution."""
    from speedfog_racing.api.stats import _stats_cache, _stats_cache_locks

    _stats_cache.clear()
    _stats_cache_locks.clear()
    yield


@pytest.fixture(scope="function")
def client():
    """Create test client."""
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
