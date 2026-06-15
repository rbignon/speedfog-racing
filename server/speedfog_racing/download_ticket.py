"""Signed, short-lived tickets for header-less seed-pack downloads.

A ticket authenticates a download GET via a URL query param instead of an
Authorization header, so the browser's native download manager can fetch the
file directly (progress, resume, no JS memory). The token is a stateless HMAC
over ``secret_key``: no DB row, no in-memory state, it survives restarts, and
it stays valid for the whole TTL so the browser's range-based resume keeps
working. ``scope`` ("race" / "training") plus the resource id binding stop a
ticket minted for one endpoint from being replayed against the other.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from uuid import UUID

from speedfog_racing.config import settings

TICKET_TTL = timedelta(minutes=10)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign(payload: str) -> str:
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).digest()
    return _b64(sig)


def sign_download_ticket(scope: str, user_id: UUID, resource_id: UUID, now: datetime) -> str:
    """Return a signed ticket binding scope + user + resource, valid for TICKET_TTL."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    exp = int((now + TICKET_TTL).timestamp())
    payload = _b64(f"{scope}:{user_id}:{resource_id}:{exp}".encode())
    return f"{payload}.{_sign(payload)}"


def verify_download_ticket(token: str, scope: str, resource_id: UUID, now: datetime) -> UUID | None:
    """Return the embedded user id if the ticket is valid for this scope/resource, else None."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload, sig = parts
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("ascii")
        tok_scope, tok_user, tok_resource, tok_exp = decoded.split(":")
        exp = int(tok_exp)
    except (ValueError, UnicodeDecodeError):
        return None
    if tok_scope != scope or tok_resource != str(resource_id):
        return None
    if int(now.timestamp()) >= exp:
        return None
    try:
        return UUID(tok_user)
    except ValueError:
        return None
