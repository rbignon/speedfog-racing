"""Discord interaction endpoint (bot webhook receiver)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from speedfog_racing.auth import require_admin
from speedfog_racing.config import settings
from speedfog_racing.discord import assign_runner_role, post_runner_message, remove_runner_role
from speedfog_racing.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(signature: str, timestamp: str, body: str) -> bool:
    """Verify Discord interaction signature using Ed25519."""
    public_key = settings.discord_public_key
    if not public_key:
        return False
    try:
        from nacl.signing import VerifyKey

        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
    except Exception:
        return False
    else:
        return True


async def _handle_component(data: dict) -> dict:  # type: ignore[type-arg]
    """Handle MESSAGE_COMPONENT interaction (button clicks)."""
    custom_id = data.get("data", {}).get("custom_id")
    user_id = data.get("member", {}).get("user", {}).get("id")

    if custom_id == "become_runner" and user_id:
        await assign_runner_role(user_id)
        return {
            "type": 4,
            "data": {"content": "You now have the **Runner** role!", "flags": 64},
        }
    if custom_id == "remove_runner" and user_id:
        await remove_runner_role(user_id)
        return {
            "type": 4,
            "data": {"content": "Runner role removed.", "flags": 64},
        }
    return {"type": 4, "data": {"content": "Unknown action.", "flags": 64}}


@router.post("/interactions", response_model=None)
async def discord_interaction(request: Request) -> dict | Response:  # type: ignore[type-arg]
    """Handle Discord interaction webhook (PING + button clicks)."""
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = (await request.body()).decode()

    if not _verify_signature(signature, timestamp, body):
        return Response(status_code=401, content="Invalid signature")

    data: dict[str, object] = await request.json()

    # PING
    if data.get("type") == 1:
        return {"type": 1}

    # MESSAGE_COMPONENT (button click)
    if data.get("type") == 3:
        return await _handle_component(data)

    return Response(status_code=400)


@router.post("/setup-runner-message")
async def setup_runner_message(user: User = Depends(require_admin)) -> dict:  # type: ignore[type-arg]
    """Post the Runner role toggle message to the configured Discord channel."""
    success = await post_runner_message()
    if not success:
        raise HTTPException(400, "Discord channel not configured or API error")
    return {"status": "ok"}
