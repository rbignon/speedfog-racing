"""Rate limiting configuration (shared across routes and main app)."""

from slowapi import Limiter
from starlette.requests import Request


def _get_real_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For (set by nginx) or fall back to direct IP."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


# default_limits applies to all routes; auth endpoints override with stricter limits.
limiter = Limiter(key_func=_get_real_ip, default_limits=["60/minute"])
