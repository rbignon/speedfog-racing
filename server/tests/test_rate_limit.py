"""Tests for client-IP extraction used by the rate limiter.

The rate limiter keys per-client limits on the IP returned here, so it must
not trust a header the client can forge. nginx sets ``X-Real-IP`` to the real
socket peer (``$remote_addr``); ``X-Forwarded-For`` has the client-supplied
value prepended and is therefore spoofable.
"""

from types import SimpleNamespace

from speedfog_racing.rate_limit import _get_real_ip


def _request(headers: dict[str, str], client_host: str | None = "10.0.0.1") -> SimpleNamespace:
    client = SimpleNamespace(host=client_host) if client_host is not None else None
    return SimpleNamespace(headers=headers, client=client)


def test_prefers_x_real_ip():
    req = _request({"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"})
    assert _get_real_ip(req) == "203.0.113.7"


def test_ignores_spoofed_forwarded_for_without_real_ip():
    # Only a forgeable X-Forwarded-For is present: it must not become the key.
    req = _request({"X-Forwarded-For": "1.2.3.4"}, client_host="10.0.0.9")
    assert _get_real_ip(req) == "10.0.0.9"


def test_falls_back_to_direct_peer():
    req = _request({}, client_host="10.0.0.9")
    assert _get_real_ip(req) == "10.0.0.9"


def test_last_resort_loopback():
    req = _request({}, client_host=None)
    assert _get_real_ip(req) == "127.0.0.1"
