"""Seed pack generation service for race participants.

Streams personalized seed packs by injecting per-participant config into
the original seed zip on-the-fly, without copying the full file.
"""

import io
import logging
import re
import struct
import time
import zlib
from collections.abc import Iterator
from pathlib import Path

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, Race, TrainingSession

logger = logging.getLogger(__name__)

OVERLAY_DEFAULTS: dict[str, float] = {"font_size": 18.0}
CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks


def _get_overlay_setting(user_settings: dict[str, float] | None, key: str) -> float:
    """Get overlay setting from user prefs or defaults."""
    if user_settings and key in user_settings:
        return float(user_settings[key])
    return OVERLAY_DEFAULTS[key]


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe use as a filename component."""
    return re.sub(r"[^a-zA-Z0-9_]", "", name) or "unknown"


# =============================================================================
# ZIP format helpers
# =============================================================================

# Signatures
_EOCD_SIG = b"PK\x05\x06"
_CD_SIG = b"PK\x01\x02"
_LOCAL_SIG = b"PK\x03\x04"


def _find_eocd(f: io.BufferedReader) -> tuple[int, int, int, int]:
    """Find and parse the End of Central Directory record.

    Returns:
        (eocd_offset, cd_offset, cd_size, num_entries)

    Raises:
        ValueError: If the file is not a valid ZIP or uses ZIP64.
    """
    f.seek(0, 2)
    file_size = f.tell()

    # EOCD is at least 22 bytes; max comment is 65535 → search last 65557 bytes
    search_start = max(0, file_size - 65557)
    f.seek(search_start)
    data = f.read()

    idx = data.rfind(_EOCD_SIG)
    if idx == -1:
        raise ValueError("Not a valid ZIP file (EOCD not found)")

    # Parse EOCD fields
    num_entries = struct.unpack_from("<H", data, idx + 10)[0]
    cd_size = struct.unpack_from("<I", data, idx + 12)[0]
    cd_offset = struct.unpack_from("<I", data, idx + 16)[0]

    # Reject ZIP64 (marker values)
    if num_entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        raise ValueError("ZIP64 is not supported")

    return search_start + idx, cd_offset, cd_size, num_entries


def _top_dir_from_cd(cd_bytes: bytes) -> str | None:
    """Extract common top-level directory from central directory entries.

    Returns the shared top-level directory only if *every* entry lives
    under the same single directory.  Returns ``None`` if any entry sits
    at the root level or entries belong to different top-level dirs.
    """
    top_dirs: set[str] = set()
    offset = 0
    while offset < len(cd_bytes):
        if cd_bytes[offset : offset + 4] != _CD_SIG:
            break
        fname_len = struct.unpack_from("<H", cd_bytes, offset + 28)[0]
        extra_len = struct.unpack_from("<H", cd_bytes, offset + 30)[0]
        comment_len = struct.unpack_from("<H", cd_bytes, offset + 32)[0]

        fname = cd_bytes[offset + 46 : offset + 46 + fname_len].decode("utf-8", errors="replace")
        if "/" in fname:
            top_dirs.add(fname.split("/")[0])
        else:
            # A file at the root → no common top-level directory
            return None

        offset += 46 + fname_len + extra_len + comment_len

    if len(top_dirs) == 1:
        return top_dirs.pop()
    return None


def _prepare_entry(filename: str, data: bytes) -> tuple[bytes, int, int]:
    """Compute shared metadata for a new ZIP entry.

    Returns ``(fname_bytes, crc, data_size)`` used by both
    the local file header and the central directory entry.
    """
    fname_bytes = filename.encode("utf-8")
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return fname_bytes, crc, len(data)


def _dos_datetime() -> tuple[int, int]:
    """Return current time as DOS date and time values."""
    t = time.localtime()
    dos_time = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    dos_date = ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    return dos_time, dos_date


def _make_local_file_header(
    fname_bytes: bytes,
    data: bytes,
    crc: int,
    dos_time: int,
    dos_date: int,
) -> bytes:
    """Build a local file header + file data (stored, no compression)."""
    header = struct.pack(
        "<4sHHHHHIIIHH",
        _LOCAL_SIG,
        20,  # version needed (2.0)
        0,  # general purpose bit flag
        0,  # compression method (stored)
        dos_time,
        dos_date,
        crc,
        len(data),  # compressed size
        len(data),  # uncompressed size
        len(fname_bytes),
        0,  # extra field length
    )
    return header + fname_bytes + data


def _make_cd_entry(
    fname_bytes: bytes,
    data_size: int,
    crc: int,
    dos_time: int,
    dos_date: int,
    local_header_offset: int,
) -> bytes:
    """Build a central directory entry for one file."""
    header = struct.pack(
        "<4sHHHHHHIIIHHHHHII",
        _CD_SIG,
        20,  # version made by
        20,  # version needed
        0,  # general purpose bit flag
        0,  # compression method (stored)
        dos_time,
        dos_date,
        crc,
        data_size,  # compressed size
        data_size,  # uncompressed size
        len(fname_bytes),
        0,  # extra field length
        0,  # file comment length
        0,  # disk number start
        0,  # internal file attributes
        0x20,  # external file attributes (archive bit)
        local_header_offset,
    )
    return header + fname_bytes


def _make_eocd(num_entries: int, cd_size: int, cd_offset: int) -> bytes:
    """Build an End of Central Directory record."""
    return struct.pack(
        "<4sHHHHIIH",
        _EOCD_SIG,
        0,  # number of this disk
        0,  # disk where CD starts
        num_entries,  # entries on this disk
        num_entries,  # total entries
        cd_size,
        cd_offset,
        0,  # comment length
    )


# =============================================================================
# Streaming seed pack
# =============================================================================


def stream_seed_pack_with_config(
    seed_zip_path: Path,
    config_content: str,
) -> tuple[Iterator[bytes], int]:
    """Stream a seed zip with an injected per-participant config.

    Reads the original zip structure, appends the config as
    ``{top_dir}/lib/speedfog_race.toml``, and streams the result
    in 64 KB chunks.  No temp files, no full-file copy.

    Args:
        seed_zip_path: Path to the original seed zip.
        config_content: TOML configuration string to inject.

    Returns:
        ``(byte_generator, total_content_length)``

    Raises:
        FileNotFoundError: If *seed_zip_path* does not exist.
        ValueError: If the file is not a valid ZIP or uses ZIP64.
    """
    # --- Phase 1: analyse (reads a few KB from end of file) ---------------
    with open(seed_zip_path, "rb") as f:
        _eocd_offset, cd_offset, cd_size, num_entries = _find_eocd(f)
        f.seek(cd_offset)
        cd_bytes = f.read(cd_size)

    top_dir = _top_dir_from_cd(cd_bytes)
    config_name = f"{top_dir}/lib/speedfog_race.toml" if top_dir else "lib/speedfog_race.toml"

    config_data = config_content.encode("utf-8")
    fname_bytes, crc, data_size = _prepare_entry(config_name, config_data)
    dos_time, dos_date = _dos_datetime()
    local_entry = _make_local_file_header(fname_bytes, config_data, crc, dos_time, dos_date)
    new_cd_entry = _make_cd_entry(
        fname_bytes, data_size, crc, dos_time, dos_date, local_header_offset=cd_offset
    )
    new_eocd = _make_eocd(
        num_entries=num_entries + 1,
        cd_size=cd_size + len(new_cd_entry),
        cd_offset=cd_offset + len(local_entry),
    )

    total_size = cd_offset + len(local_entry) + cd_size + len(new_cd_entry) + len(new_eocd)

    # --- Phase 2: streaming generator (64 KB RAM) -------------------------
    def _generate() -> Iterator[bytes]:
        with open(seed_zip_path, "rb") as f:
            remaining = cd_offset
            while remaining > 0:
                chunk_size = min(CHUNK_SIZE, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

        # New local file entry (sits right before the new central directory)
        yield local_entry

        # Original central directory entries (offsets unchanged)
        yield cd_bytes

        # New central directory entry
        yield new_cd_entry

        # Updated EOCD
        yield new_eocd

    return _generate(), total_size


# =============================================================================
# Config generation (unchanged)
# =============================================================================


def generate_player_config(
    participant: Participant,
    race: Race,
    websocket_url: str | None = None,
) -> str:
    """Generate TOML configuration content for a participant.

    Args:
        participant: The participant to generate config for
        race: The race the participant is in
        websocket_url: WebSocket URL override (defaults to settings.websocket_url)

    Returns:
        TOML-formatted configuration string
    """
    ws_url = websocket_url or settings.websocket_url

    return f"""[server]
url = "{ws_url}"
mod_token = "{participant.mod_token}"
race_id = "{race.id}"
seed_id = "{race.seed_id}"

[overlay]
enabled = true
# Font to use for the overlay. Can be:
#   - Empty "" (default): Uses Windows system font (Segoe UI)
#   - Filename only "arial.ttf": Looks in C:\\Windows\\Fonts\\ then DLL directory
#   - Relative path "fonts/custom.ttf": Relative to DLL directory
#   - Absolute path "C:\\Fonts\\MyFont.ttf": Uses the specified file
font_path = ""
# Font size in pixels (18.0 recommended for 1080p, 36.0 for 4K)
font_size = {_get_overlay_setting(participant.user.overlay_settings, "font_size")}
# Background color and opacity
background_color = "#141414"
background_opacity = 0.3
# Text colors
text_color = "#FFFFFF"
text_disabled_color = "#808080"
# Window border
show_border = false
border_color = "#404040"

[keybindings]
toggle_ui = "f9"
"""


def generate_training_config(session: TrainingSession) -> str:
    """Generate TOML config for training mod connection."""
    ws_url = settings.websocket_url
    return f"""[server]
url = "{ws_url}"
mod_token = "{session.mod_token}"
race_id = "{session.id}"
training = true

[overlay]
enabled = true
font_path = ""
font_size = {_get_overlay_setting(session.user.overlay_settings, "font_size")}
background_color = "#141414"
background_opacity = 0.3
text_color = "#FFFFFF"
text_disabled_color = "#808080"
show_border = false
border_color = "#404040"

[keybindings]
toggle_ui = "f9"
"""
