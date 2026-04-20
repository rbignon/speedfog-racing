"""Tests for the avatar cache service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from speedfog_racing.services.avatar_cache import AvatarCache


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "avatars"


async def test_fetches_and_caches_remote_avatar(cache_dir: Path) -> None:
    cache = AvatarCache(cache_dir=cache_dir, default_avatar=b"DEFAULT")

    fake_response = httpx.Response(200, content=b"PNGBYTES")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=fake_response)

    with patch("speedfog_racing.services.avatar_cache.httpx.AsyncClient") as ctor:
        ctor.return_value.__aenter__.return_value = mock_client
        result = await cache.get("https://cdn.twitch.tv/avatar-abc.png")

    assert result == b"PNGBYTES"
    cached_files = list(cache_dir.iterdir())
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == b"PNGBYTES"


async def test_returns_cached_bytes_on_second_call(cache_dir: Path) -> None:
    cache = AvatarCache(cache_dir=cache_dir, default_avatar=b"DEFAULT")
    fake_response = httpx.Response(200, content=b"PNGBYTES")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=fake_response)

    with patch("speedfog_racing.services.avatar_cache.httpx.AsyncClient") as ctor:
        ctor.return_value.__aenter__.return_value = mock_client
        await cache.get("https://cdn.twitch.tv/avatar-abc.png")
        await cache.get("https://cdn.twitch.tv/avatar-abc.png")

    assert mock_client.get.call_count == 1


async def test_returns_default_when_url_is_none(cache_dir: Path) -> None:
    cache = AvatarCache(cache_dir=cache_dir, default_avatar=b"DEFAULT")
    assert await cache.get(None) == b"DEFAULT"


async def test_returns_default_on_http_error(cache_dir: Path) -> None:
    cache = AvatarCache(cache_dir=cache_dir, default_avatar=b"DEFAULT")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=httpx.Response(404))

    with patch("speedfog_racing.services.avatar_cache.httpx.AsyncClient") as ctor:
        ctor.return_value.__aenter__.return_value = mock_client
        result = await cache.get("https://cdn.twitch.tv/missing.png")

    assert result == b"DEFAULT"


async def test_returns_default_on_timeout(cache_dir: Path) -> None:
    cache = AvatarCache(cache_dir=cache_dir, default_avatar=b"DEFAULT")
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("slow"))

    with patch("speedfog_racing.services.avatar_cache.httpx.AsyncClient") as ctor:
        ctor.return_value.__aenter__.return_value = mock_client
        result = await cache.get("https://cdn.twitch.tv/slow.png")

    assert result == b"DEFAULT"
