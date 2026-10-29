"""Seed pack generation service for race participants.

Streams personalized seed packs by injecting per-participant config and the
server's current mod DLL into the original seed zip on-the-fly, without copying
the full file.
"""

import io
import logging
import os
import re
import struct
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, Race, TrainingSession

logger = logging.getLogger(__name__)

OVERLAY_DEFAULTS: dict[str, float] = {"font_size": 20.0}
# Leaderboard layouts the mod knows (its LeaderboardMode). Only these reach the
# TOML: the mod reads an unknown one as centered, but a stray quote in the
# value would break the whole config.
LeaderboardMode = Literal["centered", "top"]
DEFAULT_LEADERBOARD_MODE: LeaderboardMode = "centered"
CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks
MOD_DLL_NAME = "speedfog_racing.dll"


class ModDllUnavailableError(Exception):
    """The server has no readable mod DLL to put in seed packs."""


@dataclass(frozen=True)
class ModDll:
    """The mod build every pack carries, read once and shared by all downloads."""

    data: bytes
    crc: int


# One entry: the server serves a single DLL, and a new build on disk replaces
# it. Keyed on (path, size, mtime) so concurrent downloads share one copy.
_mod_dll_cache: tuple[tuple[str, int, int], ModDll] | None = None


def load_mod_dll(path: Path) -> ModDll:
    """The mod DLL at ``path``, cached until the file changes.

    Raises:
        ModDllUnavailableError: If the file is missing or unreadable (kept apart
            from ``FileNotFoundError``, which means a purged seed zip).
    """
    global _mod_dll_cache
    try:
        with open(path, "rb") as f:
            # Stat the open file, so the key and the bytes come from the same inode.
            st = os.fstat(f.fileno())
            key = (str(path), st.st_size, st.st_mtime_ns)
            if _mod_dll_cache is not None and _mod_dll_cache[0] == key:
                return _mod_dll_cache[1]
            data = f.read()
    except OSError as e:
        raise ModDllUnavailableError(f"Mod DLL unavailable at {path}: {e}") from e
    dll = ModDll(data=data, crc=zlib.crc32(data) & 0xFFFFFFFF)
    _mod_dll_cache = (key, dll)
    return dll


def _get_overlay_setting(user_settings: dict[str, Any] | None, key: str) -> float:
    """Get overlay setting from user prefs or defaults."""
    if user_settings and key in user_settings:
        return float(user_settings[key])
    return OVERLAY_DEFAULTS[key]


def _get_leaderboard_mode(user_settings: dict[str, Any] | None) -> str:
    """Get the user's leaderboard layout, the default for anything the mod would not parse."""
    mode = (user_settings or {}).get("leaderboard_mode")
    return str(mode) if mode in get_args(LeaderboardMode) else DEFAULT_LEADERBOARD_MODE


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
_DATA_DESCRIPTOR_SIG = b"PK\x07\x08"

_CD_FIXED_LEN = 46  # central directory entry header, before name/extra/comment
_LOCAL_FIXED_LEN = 30  # local file header, before name/extra/data
_FLAG_DATA_DESCRIPTOR = 0x08  # general purpose bit 3: sizes/CRC trail the data


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


@dataclass(frozen=True)
class _CdEntry:
    """One parsed central directory entry (positions are relative to the CD bytes)."""

    start: int
    end: int
    name: str
    flags: int
    compressed_size: int
    local_header_offset: int


def _iter_cd_entries(cd_bytes: bytes) -> Iterator[_CdEntry]:
    """Walk the central directory, stopping at the first non-entry record."""
    offset = 0
    while offset < len(cd_bytes):
        if cd_bytes[offset : offset + 4] != _CD_SIG:
            break
        flags = struct.unpack_from("<H", cd_bytes, offset + 8)[0]
        compressed_size = struct.unpack_from("<I", cd_bytes, offset + 20)[0]
        fname_len, extra_len, comment_len = struct.unpack_from("<HHH", cd_bytes, offset + 28)
        local_header_offset = struct.unpack_from("<I", cd_bytes, offset + 42)[0]
        name_start = offset + _CD_FIXED_LEN
        fname = cd_bytes[name_start : name_start + fname_len].decode("utf-8", errors="replace")
        end = name_start + fname_len + extra_len + comment_len
        yield _CdEntry(offset, end, fname, flags, compressed_size, local_header_offset)
        offset = end


def _top_dir_from_cd(entries: list[_CdEntry]) -> str | None:
    """Extract common top-level directory from central directory entries.

    Returns the shared top-level directory only if *every* entry lives
    under the same single directory.  Returns ``None`` if any entry sits
    at the root level or entries belong to different top-level dirs.
    """
    top_dirs: set[str] = set()
    for entry in entries:
        if "/" not in entry.name:
            # A file at the root → no common top-level directory
            return None
        top_dirs.add(entry.name.split("/")[0])

    if len(top_dirs) == 1:
        return top_dirs.pop()
    return None


def _is_seed_graph_entry(name: str) -> bool:
    """Match the seed's own ``graph.json``: at the root or directly under the top dir.

    Same rule as the pool scan (``seed_service._read_graph_from_zip``): what the
    server ingests from the pool zip is exactly what players never receive. The
    DAG is a full-route spoiler and the mod needs nothing from it (everything it
    uses arrives in ``auth_ok``).
    """
    parts = name.split("/")
    return parts[-1] == "graph.json" and len(parts) <= 2


def _local_entry_span(f: io.BufferedReader, entry: _CdEntry) -> int:
    """Byte length of an entry's local record: header, name, extra, data, descriptor."""
    f.seek(entry.local_header_offset)
    header = f.read(_LOCAL_FIXED_LEN)
    if len(header) < _LOCAL_FIXED_LEN or header[:4] != _LOCAL_SIG:
        raise ValueError(f"Corrupt local file header for {entry.name!r}")
    fname_len, extra_len = struct.unpack_from("<HH", header, 26)
    span: int = _LOCAL_FIXED_LEN + fname_len + extra_len + entry.compressed_size
    if entry.flags & _FLAG_DATA_DESCRIPTOR:
        # 12 bytes (crc, compressed size, uncompressed size), 16 with the
        # optional signature most writers (including Python's zipfile) emit.
        f.seek(entry.local_header_offset + span)
        span += 16 if f.read(4) == _DATA_DESCRIPTOR_SIG else 12
    return span


def _is_mod_dll_entry(name: str) -> bool:
    """Match the mod DLL at the path ModEngine loads: ``lib/`` at the root or under the top dir.

    Pool zips generated before the server started appending the DLL carry the
    build of their generation day there; it is replaced by the current one.
    """
    parts = name.split("/")
    return parts[-2:] == ["lib", MOD_DLL_NAME] and len(parts) <= 3


def _first_entry(
    zip_name: str, entries: list[_CdEntry], match: Callable[[str], bool], label: str
) -> _CdEntry | None:
    """The first entry ``match`` accepts; several candidates are logged, only one is dropped."""
    found = [e for e in entries if match(e.name)]
    if len(found) > 1:
        # Generator output never produces this; make a leak visible if it ever does.
        logger.warning(
            "%s has %d %s candidates, only %r is dropped",
            zip_name,
            len(found),
            label,
            found[0].name,
        )
    return found[0] if found else None


def _drop_entries_from_cd(
    cd_bytes: bytes, entries: list[_CdEntry], dropped: list[tuple[_CdEntry, int]]
) -> bytes:
    """Rebuild the central directory without the ``dropped`` ``(entry, span)`` pairs.

    Each surviving entry moves back, in the streamed output, by the summed
    spans of the dropped records stored before it, so its
    ``local_header_offset`` is rewritten. Any trailing non-entry bytes are kept
    verbatim.
    """
    out = bytearray()
    for entry in entries:
        if any(entry is d for d, _ in dropped):
            continue
        chunk = bytearray(cd_bytes[entry.start : entry.end])
        shift = sum(
            span for d, span in dropped if d.local_header_offset < entry.local_header_offset
        )
        if shift:
            struct.pack_into("<I", chunk, 42, entry.local_header_offset - shift)
        out += chunk
    out += cd_bytes[entries[-1].end :]
    return bytes(out)


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
    return _make_local_header(fname_bytes, len(data), crc, dos_time, dos_date) + data


def _make_local_header(
    fname_bytes: bytes,
    data_size: int,
    crc: int,
    dos_time: int,
    dos_date: int,
) -> bytes:
    """Build a local file header and name for a stored entry, without its data.

    Lets a large entry's data be streamed from a shared buffer instead of being
    concatenated into a new object per download.
    """
    return (
        struct.pack(
            "<4sHHHHHIIIHH",
            _LOCAL_SIG,
            20,  # version needed (2.0)
            0,  # general purpose bit flag
            0,  # compression method (stored)
            dos_time,
            dos_date,
            crc,
            data_size,  # compressed size
            data_size,  # uncompressed size
            len(fname_bytes),
            0,  # extra field length
        )
        + fname_bytes
    )


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


def _stream_range(f: io.BufferedReader, start: int, end: int) -> Iterator[bytes]:
    """Yield ``f[start:end]`` in ``CHUNK_SIZE`` pieces."""
    f.seek(start)
    remaining = end - start
    while remaining > 0:
        chunk = f.read(min(CHUNK_SIZE, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        yield chunk


def stream_seed_pack_with_config(
    seed_zip_path: Path,
    config_content: str,
    mod_dll_path: Path,
) -> tuple[Iterator[bytes], int]:
    """Stream a seed zip with an injected per-participant config and the current mod.

    Reads the original zip structure, drops the seed's ``graph.json`` (see
    :func:`_is_seed_graph_entry`) and any mod DLL bundled at generation (see
    :func:`_is_mod_dll_entry`), appends the config as
    ``{top_dir}/lib/speedfog_racing.toml`` and the server's current DLL as
    ``{top_dir}/lib/speedfog_racing.dll``, and streams the result in 64 KB
    chunks.  No temp files, no full-file copy: the surviving local records
    are streamed verbatim, only the central directory is rewritten.

    Args:
        seed_zip_path: Path to the original seed zip.
        config_content: TOML configuration string to inject.
        mod_dll_path: Path to the mod DLL every pack carries.

    Returns:
        ``(byte_generator, total_content_length)``

    Raises:
        FileNotFoundError: If *seed_zip_path* does not exist.
        ValueError: If the file is not a valid ZIP or uses ZIP64.
        ModDllUnavailableError: If the mod DLL cannot be read.
    """
    logger.info("Generating seed pack from %s", seed_zip_path.name)
    # --- Phase 1: analyse (reads a few KB from end of file) ---------------
    with open(seed_zip_path, "rb") as f:
        _eocd_offset, cd_offset, cd_size, num_entries = _find_eocd(f)
        f.seek(cd_offset)
        cd_bytes = f.read(cd_size)
        entries = list(_iter_cd_entries(cd_bytes))

        # Local records to skip, as (entry, span) in local-offset order.
        dropped: list[tuple[_CdEntry, int]] = []
        for match, label in (
            (_is_seed_graph_entry, "graph.json"),
            (_is_mod_dll_entry, MOD_DLL_NAME),
        ):
            entry = _first_entry(seed_zip_path.name, entries, match, label)
            if entry is None:
                continue
            span = _local_entry_span(f, entry)
            if entry.local_header_offset + span > cd_offset:
                raise ValueError(f"Local record of {entry.name!r} overruns the central directory")
            dropped.append((entry, span))
        dropped.sort(key=lambda d: d[0].local_header_offset)
        if dropped:
            cd_bytes = _drop_entries_from_cd(cd_bytes, entries, dropped)
            num_entries -= len(dropped)

    # Loaded once here: the generator streams this exact build even if a
    # deploy replaces the file mid-download.
    mod_dll = load_mod_dll(mod_dll_path)

    top_dir = _top_dir_from_cd(entries)
    lib_dir = f"{top_dir}/lib" if top_dir else "lib"

    # Offset where the surviving local records end in the streamed output.
    local_end = cd_offset - sum(span for _, span in dropped)
    dos_time, dos_date = _dos_datetime()

    config_data = config_content.encode("utf-8")
    fname_bytes, crc, data_size = _prepare_entry(f"{lib_dir}/speedfog_racing.toml", config_data)
    config_local = _make_local_file_header(fname_bytes, config_data, crc, dos_time, dos_date)
    config_cd = _make_cd_entry(
        fname_bytes, data_size, crc, dos_time, dos_date, local_header_offset=local_end
    )

    dll_offset = local_end + len(config_local)
    dll_fname = f"{lib_dir}/{MOD_DLL_NAME}".encode()
    dll_size = len(mod_dll.data)
    dll_header = _make_local_header(dll_fname, dll_size, mod_dll.crc, dos_time, dos_date)
    dll_cd = _make_cd_entry(
        dll_fname, dll_size, mod_dll.crc, dos_time, dos_date, local_header_offset=dll_offset
    )

    new_cd_offset = dll_offset + len(dll_header) + dll_size
    new_eocd = _make_eocd(
        num_entries=num_entries + 2,
        cd_size=len(cd_bytes) + len(config_cd) + len(dll_cd),
        cd_offset=new_cd_offset,
    )

    total_size = new_cd_offset + len(cd_bytes) + len(config_cd) + len(dll_cd) + len(new_eocd)

    # --- Phase 2: streaming generator (64 KB RAM) -------------------------
    def _generate() -> Iterator[bytes]:
        with open(seed_zip_path, "rb") as f:
            start = 0
            for entry, span in dropped:
                yield from _stream_range(f, start, entry.local_header_offset)
                start = entry.local_header_offset + span
            yield from _stream_range(f, start, cd_offset)

        # New local entries (right before the new central directory): the
        # config, then the DLL sliced from the shared buffer.
        yield config_local
        yield dll_header
        for i in range(0, dll_size, CHUNK_SIZE):
            yield mod_dll.data[i : i + CHUNK_SIZE]

        # Surviving central directory entries (offsets already rewritten)
        yield cd_bytes

        # New central directory entries
        yield config_cd
        yield dll_cd

        # Updated EOCD
        yield new_eocd

    return _generate(), total_size


# =============================================================================
# Config generation (unchanged)
# =============================================================================

# Both templates below write the same [overlay] table: the font size fallback
# (OVERLAY_DEFAULTS), the colors and the background opacity equal the mod's own
# defaults, so every pack renders alike whatever mod version runs it (a pack
# downloaded before a release keeps its older DLL). Keep in sync with
# mod/src/dll/config.rs and docs/GRAPHIC_CHARTER.md.


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
# Screen corner the overlay is anchored to:
#   "top-left", "top-right", "bottom-left" or "bottom-right"
anchor = "top-right"
# Font to use for the overlay. Can be:
#   - Empty "" (default): Uses the font embedded in the mod
#   - Filename only "arial.ttf": Looks in C:\\Windows\\Fonts\\ then DLL directory
#   - Relative path "fonts/custom.ttf": Relative to DLL directory
#   - Absolute path "C:\\Fonts\\MyFont.ttf": Uses the specified file
font_path = ""
# Font size in pixels (20.0 recommended for 1080p, 40.0 for 4K)
font_size = {_get_overlay_setting(participant.user.overlay_settings, "font_size")}
# Leaderboard layout the overlay starts on (F10 cycles it, hidden, then the other):
#   "centered": top 3, then you between the three runners ahead and behind,
#               gaps relative to you
#   "top": top 10, gaps relative to the leader
leaderboard_mode = "{_get_leaderboard_mode(participant.user.overlay_settings)}"
# Background color and opacity
background_color = "#0F1923"
background_opacity = 0.55
# Text colors
text_color = "#E8E6E1"
text_disabled_color = "#96A0AD"
# Window border
show_border = false
border_color = "#253550"

[keybindings]
toggle_ui = "f9"
toggle_leaderboard = "f10"
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
# Screen corner the overlay is anchored to:
#   "top-left", "top-right", "bottom-left" or "bottom-right"
anchor = "top-right"
font_path = ""
font_size = {_get_overlay_setting(session.user.overlay_settings, "font_size")}
leaderboard_mode = "{_get_leaderboard_mode(session.user.overlay_settings)}"
background_color = "#0F1923"
background_opacity = 0.55
text_color = "#E8E6E1"
text_disabled_color = "#96A0AD"
show_border = false
border_color = "#253550"

[keybindings]
toggle_ui = "f9"
toggle_leaderboard = "f10"
"""
