"""Test seed pack generation service."""

import io
import json
import os
import struct
import tempfile
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from speedfog_racing.services.seed_pack_service import (
    _iter_cd_entries,
    generate_player_config,
    stream_seed_pack_with_config,
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
            zf.writestr("speedfog_abc123/lib/speedfog_racing.dll", "mock dll")
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
# Streaming Seed Pack Tests
# =============================================================================


def _collect_stream(seed_zip_path: Path, config: str) -> tuple[bytes, int]:
    """Helper: collect streamed bytes and declared content length."""
    stream, content_length = stream_seed_pack_with_config(seed_zip_path, config)
    data = b"".join(stream)
    return data, content_length


def test_stream_produces_valid_zip(seed_zip):
    """Streamed output should be a valid ZIP file."""
    data, _ = _collect_stream(seed_zip, "[server]\ntest = true\n")
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert zf.testzip() is None
    zf.close()


def test_stream_content_length_matches(seed_zip):
    """Declared content length should match actual bytes."""
    data, content_length = _collect_stream(seed_zip, "[server]\ntest = true\n")
    assert len(data) == content_length


def test_stream_contains_original_files(seed_zip):
    """Streamed zip should contain all original files."""
    data, _ = _collect_stream(seed_zip, "[server]\ntest = true\n")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "speedfog_abc123/lib/speedfog_racing.dll" in names
        assert "speedfog_abc123/ModEngine/config_eldenring.toml" in names
        assert "speedfog_abc123/launch_speedfog.bat" in names


def test_stream_contains_injected_config(seed_zip):
    """Streamed zip should contain the injected config TOML."""
    config = '[server]\nmod_token = "abc123"\n'
    data, _ = _collect_stream(seed_zip, config)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert "speedfog_abc123/lib/speedfog_racing.toml" in zf.namelist()
        content = zf.read("speedfog_abc123/lib/speedfog_racing.toml").decode()
        assert 'mod_token = "abc123"' in content


def test_stream_original_file_contents_intact(seed_zip):
    """Original file contents should be preserved byte-for-byte."""
    data, _ = _collect_stream(seed_zip, "[server]\n")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.read("speedfog_abc123/lib/speedfog_racing.dll") == b"mock dll"
        assert zf.read("speedfog_abc123/launch_speedfog.bat") == b"@echo off\necho Launch"


def test_stream_does_not_modify_original(seed_zip):
    """Original seed zip should not be modified."""
    original_mtime = os.path.getmtime(seed_zip)
    original_size = os.path.getsize(seed_zip)

    _collect_stream(seed_zip, "[server]\n")

    assert os.path.getmtime(seed_zip) == original_mtime
    assert os.path.getsize(seed_zip) == original_size


def test_stream_missing_zip_raises():
    """Should raise FileNotFoundError for non-existent zip."""
    with pytest.raises(FileNotFoundError):
        _collect_stream(Path("/nonexistent/path.zip"), "[server]\n")


def test_stream_invalid_zip_raises():
    """Should raise ValueError for non-ZIP file."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(b"not a zip file")
        f.flush()
        try:
            with pytest.raises(ValueError, match="Not a valid ZIP"):
                _collect_stream(Path(f.name), "[server]\n")
        finally:
            os.unlink(f.name)


def test_stream_zip_without_top_dir():
    """Flat zips get the config at lib/ and lose their root-level graph.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "flat.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("lib/mod.dll", "dll")
            zf.writestr("graph.json", "{}")

        data, _ = _collect_stream(zip_path, "[server]\n")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert "lib/speedfog_racing.toml" in zf.namelist()
            assert "graph.json" not in zf.namelist()
            assert zf.read("lib/mod.dll") == b"dll"


def test_stream_larger_config(seed_zip):
    """Should handle configs of various sizes correctly."""
    config = "[server]\n" + "# padding\n" * 500  # ~5 KB config
    data, content_length = _collect_stream(seed_zip, config)
    assert len(data) == content_length

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        stored = zf.read("speedfog_abc123/lib/speedfog_racing.toml").decode()
        assert stored == config


def test_stream_with_deflated_entries():
    """Deflated entries in the original zip should survive the round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "deflated.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("top/lib/mod.dll", "x" * 10000)
            zf.writestr("top/graph.json", json.dumps({"nodes": list(range(100))}))

        data, content_length = _collect_stream(zip_path, "[server]\n")
        assert len(data) == content_length

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert zf.read("top/lib/mod.dll") == b"x" * 10000
            assert "top/lib/speedfog_racing.toml" in zf.namelist()


# =============================================================================
# graph.json stripping
# =============================================================================


def test_stream_strips_graph_json(seed_zip):
    """The DAG definition must not ship to players: it is a full-route spoiler."""
    data, content_length = _collect_stream(seed_zip, "[server]\n")
    assert len(data) == content_length
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        assert "speedfog_abc123/graph.json" not in zf.namelist()


def test_stream_strips_graph_json_between_other_entries():
    """Entries stored after graph.json must keep working once its bytes are dropped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "middle.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("top/a.txt", "a" * 3000)
            zf.writestr("top/graph.json", json.dumps({"nodes": list(range(500))}))
            zf.writestr("top/z.txt", "z" * 3000)

        data, content_length = _collect_stream(zip_path, "[server]\n")
        assert len(data) == content_length

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert zf.namelist() == ["top/a.txt", "top/z.txt", "top/lib/speedfog_racing.toml"]
            assert zf.read("top/a.txt") == b"a" * 3000
            assert zf.read("top/z.txt") == b"z" * 3000


def test_stream_without_graph_json_keeps_everything():
    """A zip that never had a graph.json streams through untouched."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "nograph.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("top/lib/mod.dll", "dll")
            zf.writestr("top/launch.bat", "bat")

        data, content_length = _collect_stream(zip_path, "[server]\n")
        assert len(data) == content_length

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert zf.namelist() == [
                "top/lib/mod.dll",
                "top/launch.bat",
                "top/lib/speedfog_racing.toml",
            ]


def test_stream_keeps_deeper_graph_json():
    """Only the seed's own graph.json (root or top_dir level) is stripped, same rule as the scan."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "deep.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("top/lib/mod.dll", "dll")
            zf.writestr("top/docs/graph.json", "{}")

        data, _ = _collect_stream(zip_path, "[server]\n")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert "top/docs/graph.json" in zf.namelist()


class _UnseekableWriter(io.RawIOBase):
    """Write-only wrapper that refuses to seek, forcing zipfile to emit data descriptors."""

    def __init__(self, target: io.BufferedIOBase) -> None:
        self._target = target

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        return self._target.write(b)

    def seekable(self) -> bool:
        return False

    def seek(self, *args) -> int:
        raise OSError("unseekable")

    def tell(self) -> int:
        return self._target.tell()


def test_stream_strips_graph_json_with_data_descriptor():
    """Entries written with a trailing data descriptor (flag bit 3) span extra bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "descriptor.zip"
        with open(zip_path, "wb") as raw:
            with zipfile.ZipFile(
                _UnseekableWriter(raw), "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                zf.writestr("top/graph.json", json.dumps({"nodes": list(range(500))}))
                zf.writestr("top/lib/mod.dll", "x" * 5000)

        with zipfile.ZipFile(zip_path) as src:
            assert src.getinfo("top/graph.json").flag_bits & 0x08, (
                "fixture must use data descriptors"
            )

        data, content_length = _collect_stream(zip_path, "[server]\n")
        assert len(data) == content_length

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert "top/graph.json" not in zf.namelist()
            assert zf.read("top/lib/mod.dll") == b"x" * 5000


def _reverse_central_directory(zip_path: Path) -> None:
    """Rewrite a comment-free zip so its central directory lists entries in reverse.

    The ZIP spec does not require the central directory to follow local record
    order; stdlib writers always do, so this is the only way to exercise the
    divergence.
    """
    data = bytearray(zip_path.read_bytes())
    eocd = len(data) - 22
    assert data[eocd : eocd + 4] == b"PK\x05\x06"
    cd_size, cd_offset = struct.unpack_from("<II", data, eocd + 12)
    cd = bytes(data[cd_offset : cd_offset + cd_size])
    entries = list(_iter_cd_entries(cd))
    reordered = b"".join(cd[e.start : e.end] for e in reversed(entries))
    assert len(reordered) == cd_size
    data[cd_offset : cd_offset + cd_size] = reordered
    zip_path.write_bytes(bytes(data))


def test_stream_shifts_by_local_offset_not_central_directory_order():
    """Offsets are rewritten for records stored after graph.json, whatever the CD order."""
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "reversed.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("top/a.txt", "a" * 3000)
            zf.writestr("top/graph.json", json.dumps({"nodes": list(range(500))}))
            zf.writestr("top/z.txt", "z" * 3000)
        _reverse_central_directory(zip_path)
        with zipfile.ZipFile(zip_path) as src:
            assert src.namelist() == ["top/z.txt", "top/graph.json", "top/a.txt"]

        data, content_length = _collect_stream(zip_path, "[server]\n")
        assert len(data) == content_length

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.testzip() is None
            assert "top/graph.json" not in zf.namelist()
            assert zf.read("top/a.txt") == b"a" * 3000
            assert zf.read("top/z.txt") == b"z" * 3000
