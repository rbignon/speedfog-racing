"""Rate limiting configuration (shared across routes and main app)."""

from slowapi import Limiter
from starlette.requests import Request


def _get_real_ip(request: Request) -> str:
    """Extract the client IP for rate-limit keying.

    Trusts ``X-Real-IP`` (nginx sets it to the real socket peer via
    ``$remote_addr``). ``X-Forwarded-For`` is deliberately ignored: nginx
    prepends the client-supplied value, so its leftmost element is spoofable
    and would let a client defeat every per-IP limit by rotating the header.
    """
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


# default_limits applies to all routes; auth endpoints override with stricter limits.
limiter = Limiter(key_func=_get_real_ip, default_limits=["60/minute"])
