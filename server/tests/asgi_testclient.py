"""Socket-free ASGI test client for HTTP and WebSocket tests."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import anyio
import starlette.responses as starlette_responses
from httpx import Request, Response
from starlette.websockets import WebSocketDisconnect

_ITERATE_PATCH_LOCK = threading.Lock()


class TestClient:
    """Minimal sync client compatible with the subset used by our tests."""

    __test__ = False

    def __init__(
        self,
        app: Any,
        *,
        raise_server_exceptions: bool = True,
        base_url: str = "http://testserver",
    ) -> None:
        self.app = app
        self.raise_server_exceptions = raise_server_exceptions
        self.base_url = base_url
        self._ws_loop: asyncio.AbstractEventLoop | None = None

    def __enter__(self) -> TestClient:
        self._ws_loop = asyncio.new_event_loop()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ws_loop is not None and not self._ws_loop.is_running():
            self._ws_loop.close()
        self._ws_loop = None
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        async def _request() -> Response:
            url_obj = urlsplit(url)
            body = b""
            headers_map = dict(kwargs.get("headers") or {})
            if "json" in kwargs:
                body = json.dumps(kwargs["json"]).encode("utf-8")
                headers_map.setdefault("content-type", "application/json")
            elif "content" in kwargs:
                raw = kwargs["content"]
                body = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")

            headers = [
                (k.lower().encode("latin-1"), str(v).encode("latin-1"))
                for k, v in headers_map.items()
            ]
            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": method.upper(),
                "headers": headers,
                "scheme": "http",
                "path": url_obj.path,
                "raw_path": url_obj.path.encode(),
                "query_string": url_obj.query.encode(),
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "root_path": "",
            }

            request_sent = False
            status_code: int | None = None
            response_headers: list[tuple[bytes, bytes]] = []
            response_body = bytearray()

            async def receive() -> dict[str, Any]:
                nonlocal request_sent
                if request_sent:
                    return {"type": "http.disconnect"}
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            async def send(message: dict[str, Any]) -> None:
                nonlocal status_code, response_headers
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    response_headers = message.get("headers", [])
                elif message["type"] == "http.response.body":
                    response_body.extend(message.get("body", b""))

            with _ITERATE_PATCH_LOCK:
                original_iterate_in_threadpool = starlette_responses.iterate_in_threadpool

                async def _iterate_inline(iterator: Any):
                    for item in iterator:
                        yield item

                starlette_responses.iterate_in_threadpool = _iterate_inline
                try:
                    await self.app(scope, receive, send)
                except Exception:
                    if self.raise_server_exceptions:
                        raise
                    status_code = 500
                    response_headers = []
                    response_body = bytearray()
                finally:
                    starlette_responses.iterate_in_threadpool = original_iterate_in_threadpool

            assert status_code is not None
            response = Response(
                status_code,
                headers=response_headers,
                content=bytes(response_body),
                request=Request(method.upper(), f"{self.base_url}{url}"),
            )
            return response

        return anyio.run(_request)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)

    def websocket_connect(self, path: str) -> WebSocketSession:
        assert self._ws_loop is not None
        return WebSocketSession(
            self.app,
            self._ws_loop,
            path,
            raise_server_exceptions=self.raise_server_exceptions,
        )


@dataclass
class _Queues:
    incoming: asyncio.Queue[dict[str, Any]]
    outgoing: asyncio.Queue[dict[str, Any]]


class WebSocketSession(AbstractContextManager["WebSocketSession"]):
    """Sync wrapper around a WebSocket ASGI session."""

    def __init__(
        self,
        app: Any,
        loop: asyncio.AbstractEventLoop,
        path: str,
        *,
        raise_server_exceptions: bool,
    ) -> None:
        self.app = app
        self.loop = loop
        self.path = path
        self.raise_server_exceptions = raise_server_exceptions
        self._queues: _Queues | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def __enter__(self) -> WebSocketSession:
        self.loop.run_until_complete(self._connect())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._closed and not self.loop.is_running():
            self.loop.run_until_complete(self._disconnect())

    async def _connect(self) -> None:
        qs = urlsplit(self.path)
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "scheme": "ws",
            "method": "GET",
            "path": qs.path,
            "raw_path": qs.path.encode(),
            "query_string": qs.query.encode(),
            "root_path": "",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
            "state": {},
        }
        queues = _Queues(asyncio.Queue(), asyncio.Queue())
        self._queues = queues

        async def receive() -> dict[str, Any]:
            return await queues.incoming.get()

        async def send(message: dict[str, Any]) -> None:
            await queues.outgoing.put(message)

        self._task = self.loop.create_task(self.app(scope, receive, send))
        await queues.incoming.put({"type": "websocket.connect"})
        msg = await self._next_outgoing()
        if msg["type"] == "websocket.accept":
            return
        if msg["type"] == "websocket.close":
            self._closed = True
            raise WebSocketDisconnect(code=msg.get("code", 1000), reason=msg.get("reason"))
        raise RuntimeError(f"Unexpected WebSocket handshake message: {msg}")

    async def _disconnect(self) -> None:
        assert self._queues is not None
        await self._queues.incoming.put({"type": "websocket.disconnect", "code": 1000})
        self._closed = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

    async def _next_outgoing(self) -> dict[str, Any]:
        assert self._queues is not None
        while True:
            if self._task is not None and self._task.done() and self._queues.outgoing.empty():
                exc = self._task.exception()
                if exc is not None and self.raise_server_exceptions:
                    raise exc
                raise WebSocketDisconnect(code=1011)
            try:
                return await asyncio.wait_for(self._queues.outgoing.get(), timeout=5)
            except TimeoutError:
                if self._task is not None and self._task.done():
                    exc = self._task.exception()
                    if exc is not None and self.raise_server_exceptions:
                        raise exc
                    raise WebSocketDisconnect(code=1011)

    def send_text(self, data: str) -> None:
        assert self._queues is not None
        self.loop.run_until_complete(
            self._queues.incoming.put({"type": "websocket.receive", "text": data})
        )

    def send_json(self, data: Any) -> None:
        self.send_text(json.dumps(data))

    def receive_json(self) -> Any:
        msg = self.loop.run_until_complete(self._next_outgoing())
        if msg["type"] == "websocket.send":
            text = msg.get("text")
            if text is None and msg.get("bytes") is not None:
                text = msg["bytes"].decode()
            return json.loads(text or "null")
        if msg["type"] == "websocket.close":
            self._closed = True
            raise WebSocketDisconnect(code=msg.get("code", 1000), reason=msg.get("reason"))
        raise RuntimeError(f"Unexpected WebSocket message: {msg}")
