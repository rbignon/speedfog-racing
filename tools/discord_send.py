#!/usr/bin/env python3
"""Send a message to a Discord channel via the bot.

Usage:
    uv run tools/discord_send.py <channel_id> <message>
    uv run tools/discord_send.py <channel_id>              # opens $EDITOR or reads stdin
    echo "hello" | uv run tools/discord_send.py <channel_id>

Requires DISCORD_BOT_TOKEN in server/.env (or as environment variable).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_MAX_LENGTH = 2000


def get_bot_token() -> str:
    """Read bot token from environment or server/.env file."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        return token

    env_file = Path(__file__).resolve().parent.parent / "server" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("\"'")
                if token:
                    return token

    print(
        "Error: DISCORD_BOT_TOKEN not found in environment or server/.env",
        file=sys.stderr,
    )
    sys.exit(1)


def get_message_from_editor() -> str:
    """Open $EDITOR with a temp file and return its contents."""
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w+", delete=False) as f:
        tmp_path = f.name

    try:
        result = subprocess.run([editor, tmp_path])
        if result.returncode != 0:
            print("Editor exited with error, aborting.", file=sys.stderr)
            sys.exit(1)
        with open(tmp_path) as f:
            return f.read().rstrip("\n")
    finally:
        os.unlink(tmp_path)


def get_message_interactive() -> str:
    """Get message content when no message argument is provided."""
    # Piped input
    if not sys.stdin.isatty():
        return sys.stdin.read().rstrip("\n")

    # $EDITOR / $VISUAL, fallback to vi
    return get_message_from_editor()


def send_message(channel_id: str, content: str, bot_token: str) -> None:
    """Send a message to a Discord channel."""
    response = httpx.post(
        f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
        json={"content": content},
        headers={"Authorization": f"Bot {bot_token}"},
        timeout=10.0,
    )
    if response.status_code == 200:
        print(f"Message sent to channel {channel_id}")
    else:
        print(f"Error {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a message to a Discord channel via the bot"
    )
    parser.add_argument("channel_id", help="Discord channel ID")
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Message content (omit to use $EDITOR or stdin)",
    )
    args = parser.parse_args()

    if not args.channel_id.isdigit():
        print("Error: channel_id must be numeric", file=sys.stderr)
        sys.exit(1)

    message = args.message if args.message else get_message_interactive()
    if not message.strip():
        print("Empty message, aborting.", file=sys.stderr)
        sys.exit(1)

    if len(message) > DISCORD_MAX_LENGTH:
        print(
            f"Error: message too long ({len(message)} chars, max {DISCORD_MAX_LENGTH})",
            file=sys.stderr,
        )
        sys.exit(1)

    bot_token = get_bot_token()
    send_message(args.channel_id, message, bot_token)


if __name__ == "__main__":
    main()
