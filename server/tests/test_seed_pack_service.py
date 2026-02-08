"""Test seed pack generation service."""

import json
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Participant, Race, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.seed_pack_service import (
    generate_participant_seed_pack,
    generate_player_config,
    generate_race_seed_packs,
)

# =============================================================================
# Mock Objects for Unit Tests (avoid SQLAlchemy lazy loading issues)
# =============================================================================


@dataclass
class MockUser:
    """Mock user for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    twitch_username: str = "testplayer"
    twitch_display_name: str = "Test Player"


@dataclass
class MockSeed:
    """Mock seed for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    seed_number: int = 123456
    pool_name: str = "standard"
    folder_path: str = "/test/seed"
    total_layers: int = 10


@dataclass
class MockParticipant:
    """Mock participant for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    mod_token: str = "test_mod_token_12345"
    user: MockUser = field(default_factory=MockUser)


@dataclass
class MockRace:
    """Mock race for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "Test Race"
    seed: MockSeed | None = field(default_factory=MockSeed)
    participants: list = field(default_factory=list)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def seed_folder():
    """Create a temporary seed folder with mock content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        seed_dir = Path(tmpdir) / "seed_123456"
        seed_dir.mkdir()

        # Create mock seed content matching real seed structure
        (seed_dir / "lib").mkdir()
        (seed_dir / "lib" / "speedfog_race_mod.dll").write_text("mock dll")

        (seed_dir / "ModEngine").mkdir()
        (seed_dir / "ModEngine" / "config_eldenring.toml").write_text("[config]")

        (seed_dir / "graph.json").write_text(json.dumps({"total_layers": 10, "nodes": []}))
        (seed_dir / "launch_speedfog.bat").write_text("@echo off\necho Launch")

        yield seed_dir


@pytest.fixture
def output_dir():
    """Create a temporary output directory for seed packs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_user():
    """Create a mock user."""
    return MockUser()


@pytest.fixture
def mock_seed(seed_folder):
    """Create a mock seed pointing to real folder."""
    return MockSeed(folder_path=str(seed_folder))


@pytest.fixture
def mock_race(mock_seed):
    """Create a mock race."""
    return MockRace(seed=mock_seed)


@pytest.fixture
def mock_participant(mock_user):
    """Create a mock participant."""
    return MockParticipant(user=mock_user)


# =============================================================================
# Config Generation Tests
# =============================================================================


def test_generate_player_config_format(mock_participant, mock_race):
    """Config should be valid TOML with correct values."""
    config = generate_player_config(mock_participant, mock_race)

    assert "[server]" in config
    assert f'mod_token = "{mock_participant.mod_token}"' in config
    assert f'race_id = "{mock_race.id}"' in config
    assert "[overlay]" in config
    assert "enabled = true" in config
    assert "[keybindings]" in config
    assert 'toggle_ui = "f9"' in config


def test_generate_player_config_custom_websocket_url(mock_participant, mock_race):
    """Config should use custom websocket URL if provided."""
    config = generate_player_config(
        mock_participant, mock_race, websocket_url="wss://custom.example.com"
    )

    assert 'url = "wss://custom.example.com"' in config


# =============================================================================
# Seed Pack Generation Tests
# =============================================================================


def test_generate_participant_seed_pack_creates_file(
    mock_participant, mock_race, mock_seed, seed_folder, output_dir
):
    """Generates a seed pack file in the output directory."""
    mock_race.seed = mock_seed

    seed_pack_path = generate_participant_seed_pack(mock_participant, mock_race, output_dir)

    assert seed_pack_path.exists()
    assert seed_pack_path.name == "testplayer.zip"
    assert seed_pack_path.parent == output_dir


def test_generate_participant_seed_pack_contents(
    mock_participant, mock_race, mock_seed, seed_folder, output_dir
):
    """Seed pack should contain seed contents plus config file."""
    mock_race.seed = mock_seed

    seed_pack_path = generate_participant_seed_pack(mock_participant, mock_race, output_dir)

    with zipfile.ZipFile(seed_pack_path, "r") as zf:
        names = zf.namelist()

        # Check for expected files
        assert "speedfog_123456/lib/speedfog_race_mod.dll" in names
        assert "speedfog_123456/ModEngine/config_eldenring.toml" in names
        assert "speedfog_123456/graph.json" in names
        assert "speedfog_123456/launch_speedfog.bat" in names
        assert "speedfog_123456/lib/speedfog_race.toml" in names

        # Check config content
        config_content = zf.read("speedfog_123456/lib/speedfog_race.toml").decode()
        assert mock_participant.mod_token in config_content


def test_generate_participant_seed_pack_overwrites_existing(
    mock_participant, mock_race, mock_seed, seed_folder, output_dir
):
    """Generating seed pack again overwrites the existing file."""
    mock_race.seed = mock_seed

    seed_pack_path1 = generate_participant_seed_pack(mock_participant, mock_race, output_dir)
    mtime1 = seed_pack_path1.stat().st_mtime

    # Generate again
    import time

    time.sleep(0.01)  # Ensure different mtime
    seed_pack_path2 = generate_participant_seed_pack(mock_participant, mock_race, output_dir)

    assert seed_pack_path1 == seed_pack_path2
    assert seed_pack_path2.stat().st_mtime > mtime1


def test_generate_participant_seed_pack_no_seed_raises(mock_participant, mock_race, output_dir):
    """Raises ValueError if race has no seed."""
    mock_race.seed = None

    with pytest.raises(ValueError, match="no seed assigned"):
        generate_participant_seed_pack(mock_participant, mock_race, output_dir)


def test_generate_participant_seed_pack_missing_folder_raises(
    mock_participant, mock_race, mock_seed, output_dir
):
    """Raises FileNotFoundError if seed folder doesn't exist."""
    mock_seed.folder_path = "/nonexistent/path"
    mock_race.seed = mock_seed

    with pytest.raises(FileNotFoundError):
        generate_participant_seed_pack(mock_participant, mock_race, output_dir)


# =============================================================================
# Race Seed Packs Generation Tests (integration with real DB)
# =============================================================================


@pytest.fixture
async def async_db():
    """Create async test database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def db_user(async_db):
    """Create a test user in the database."""
    user = User(
        twitch_id="123",
        twitch_username="testplayer",
        twitch_display_name="Test Player",
        role=UserRole.USER,
    )
    async_db.add(user)
    await async_db.flush()
    return user


@pytest.fixture
async def db_seed(async_db, seed_folder):
    """Create a seed record pointing to the mock folder."""
    seed = Seed(
        seed_number=123456,
        pool_name="standard",
        graph_json={"total_layers": 10, "nodes": []},
        total_layers=10,
        folder_path=str(seed_folder),
        status=SeedStatus.CONSUMED,
    )
    async_db.add(seed)
    await async_db.flush()
    return seed


@pytest.fixture
async def db_race_with_participant(async_db, db_user, db_seed):
    """Create a race with a participant, eagerly loaded."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    race = Race(
        name="Test Race",
        organizer_id=db_user.id,
        seed_id=db_seed.id,
    )
    async_db.add(race)
    await async_db.flush()

    participant = Participant(
        race_id=race.id,
        user_id=db_user.id,
    )
    async_db.add(participant)
    await async_db.commit()

    # Reload with relationships
    result = await async_db.execute(
        select(Race)
        .where(Race.id == race.id)
        .options(
            selectinload(Race.seed),
            selectinload(Race.participants).selectinload(Participant.user),
        )
    )
    loaded_race = result.scalar_one()

    return loaded_race


@pytest.mark.asyncio
async def test_generate_race_seed_packs(async_db, db_race_with_participant, output_dir):
    """Generates seed packs for all participants in a race."""
    with patch("speedfog_racing.services.seed_pack_service.settings") as mock_settings:
        mock_settings.seed_packs_output_dir = str(output_dir)
        mock_settings.websocket_url = "ws://test:8000"

        results = await generate_race_seed_packs(async_db, db_race_with_participant)

        assert len(results) == 1

        participant = db_race_with_participant.participants[0]
        assert participant.id in results

        seed_pack_path = results[participant.id]
        assert seed_pack_path.exists()


@pytest.mark.asyncio
async def test_generate_race_seed_packs_creates_race_directory(
    async_db, db_race_with_participant, output_dir
):
    """Creates a directory for the race in output dir."""
    with patch("speedfog_racing.services.seed_pack_service.settings") as mock_settings:
        mock_settings.seed_packs_output_dir = str(output_dir)
        mock_settings.websocket_url = "ws://test:8000"

        await generate_race_seed_packs(async_db, db_race_with_participant)

        race_dir = output_dir / str(db_race_with_participant.id)
        assert race_dir.exists()
        assert race_dir.is_dir()


@pytest.mark.asyncio
async def test_generate_race_seed_packs_no_seed_raises(async_db, mock_participant, output_dir):
    """Raises ValueError if race has no seed."""
    # Use mock objects to avoid SQLAlchemy lazy loading
    mock_race = MockRace(seed=None, participants=[mock_participant])

    with pytest.raises(ValueError, match="no seed assigned"):
        await generate_race_seed_packs(async_db, mock_race)


@pytest.mark.asyncio
async def test_generate_race_seed_packs_no_participants_raises(async_db, mock_seed, output_dir):
    """Raises ValueError if race has no participants."""
    # Use mock objects to avoid SQLAlchemy lazy loading
    mock_race = MockRace(seed=mock_seed, participants=[])

    with pytest.raises(ValueError, match="no participants"):
        await generate_race_seed_packs(async_db, mock_race)
