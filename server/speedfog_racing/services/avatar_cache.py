"""Disk-backed cache for remote (Twitch) avatar bytes used by OG renders."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 2.0


class AvatarCache:
    """Fetch remote avatars once and serve cached bytes thereafter.

    On any failure (missing URL, HTTP error, timeout, decode error) the
    caller-provided ``default_avatar`` bytes are returned so OG rendering
    never breaks because of an upstream issue.
    """

    def __init__(self, cache_dir: Path, default_avatar: bytes) -> None:
        self._cache_dir = cache_dir
        self._default = default_avatar
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self._cache_dir / f"{digest}.bin"

    async def get(self, url: str | None) -> bytes:
        if not url:
            return self._default
        path = self._path_for(url)
        if path.exists():
            return path.read_bytes()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
            if response.status_code != 200:
                logger.warning("avatar fetch %s -> %d", url, response.status_code)
                return self._default
            data = response.content
            path.write_bytes(data)
            return data
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("avatar fetch failed %s: %s", url, exc)
            return self._default
