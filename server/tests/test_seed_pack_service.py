"""Test seed pack generation service."""

import json
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from speedfog_racing.services.seed_pack_service import (
    generate_player_config,
    generate_seed_pack_on_demand,
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
    overlay_settings: dict | None = None


@dataclass
class MockSeed:
    """Mock seed for testing."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    seed_number: str = "abc123"
    pool_name: str = "standard"
    folder_path: str = "/test/seed.zip"
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
    seed_id: uuid.UUID | None = None
    participants: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.seed_id is None and self.seed is not None:
            self.seed_id = self.seed.id


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def seed_zip():
    """Create a temporary seed zip file with mock content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "seed_abc123.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("speedfog_abc123/lib/speedfog_race_mod.dll", "mock dll")
            zf.writestr("speedfog_abc123/ModEngine/config_eldenring.toml", "[config]")
            zf.writestr(
                "speedfog_abc123/graph.json",
                json.dumps({"total_layers": 10, "nodes": []}),
            )
            zf.writestr("speedfog_abc123/launch_speedfog.bat", "@echo off\necho Launch")
        yield zip_path


@pytest.fixture
def mock_user():
    """Create a mock user."""
    return MockUser()


@pytest.fixture
def mock_seed(seed_zip):
    """Create a mock seed pointing to real zip."""
    return MockSeed(folder_path=str(seed_zip))


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
    assert f'seed_id = "{mock_race.seed_id}"' in config
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


def test_generate_player_config_uses_user_font_size(mock_participant, mock_race):
    """Config should use user's font_size when set."""
    mock_participant.user.overlay_settings = {"font_size": 24.0}
    config = generate_player_config(mock_participant, mock_race)
    assert "font_size = 24.0" in config


def test_generate_player_config_uses_default_font_size(mock_participant, mock_race):
    """Config should use 18.0 default when user has no settings."""
    mock_participant.user.overlay_settings = None
    config = generate_player_config(mock_participant, mock_race)
    assert "font_size = 18.0" in config


# =============================================================================
# On-Demand Generation Tests
# =============================================================================


def test_generate_seed_pack_on_demand_creates_zip(mock_participant, mock_race):
    """Generates a temporary zip file."""
    temp_path = generate_seed_pack_on_demand(mock_participant, mock_race)
    try:
        assert temp_path.exists()
        assert temp_path.suffix == ".zip"
    finally:
        temp_path.unlink(missing_ok=True)


def test_generate_seed_pack_on_demand_contains_config(mock_participant, mock_race):
    """Generated zip should contain the injected config TOML."""
    temp_path = generate_seed_pack_on_demand(mock_participant, mock_race)
    try:
        with zipfile.ZipFile(temp_path, "r") as zf:
            names = zf.namelist()

            # Original files should be present
            assert "speedfog_abc123/lib/speedfog_race_mod.dll" in names
            assert "speedfog_abc123/graph.json" in names
            assert "speedfog_abc123/launch_speedfog.bat" in names

            # Injected config should be present
            assert "speedfog_abc123/lib/speedfog_race.toml" in names

            # Check config content
            config_content = zf.read("speedfog_abc123/lib/speedfog_race.toml").decode()
            assert mock_participant.mod_token in config_content
            assert str(mock_race.id) in config_content
    finally:
        temp_path.unlink(missing_ok=True)


def test_generate_seed_pack_on_demand_no_seed_raises(mock_participant, mock_race):
    """Raises ValueError if race has no seed."""
    mock_race.seed = None

    with pytest.raises(ValueError, match="no seed assigned"):
        generate_seed_pack_on_demand(mock_participant, mock_race)


def test_generate_seed_pack_on_demand_missing_zip_raises(mock_participant, mock_race, mock_seed):
    """Raises FileNotFoundError if seed zip doesn't exist."""
    mock_seed.folder_path = "/nonexistent/path.zip"
    mock_race.seed = mock_seed

    with pytest.raises(FileNotFoundError):
        generate_seed_pack_on_demand(mock_participant, mock_race)


def test_generate_seed_pack_on_demand_preserves_original(mock_participant, mock_race, seed_zip):
    """Original seed zip should not be modified."""
    import os

    original_mtime = os.path.getmtime(seed_zip)
    original_size = os.path.getsize(seed_zip)

    temp_path = generate_seed_pack_on_demand(mock_participant, mock_race)
    try:
        # Original should be untouched
        assert os.path.getmtime(seed_zip) == original_mtime
        assert os.path.getsize(seed_zip) == original_size

        # Temp file should be larger (has injected config)
        assert os.path.getsize(temp_path) > original_size
    finally:
        temp_path.unlink(missing_ok=True)
