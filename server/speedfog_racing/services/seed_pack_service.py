"""Seed pack generation service for race participants."""

import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, Race

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe use as a filename component."""
    return re.sub(r"[^a-zA-Z0-9_]", "", name) or "unknown"


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

[overlay]
enabled = true
# Font to use for the overlay. Can be:
#   - Empty "" (default): Uses Windows system font (Segoe UI)
#   - Filename only "arial.ttf": Looks in C:\\Windows\\Fonts\\ then DLL directory
#   - Relative path "fonts/custom.ttf": Relative to DLL directory
#   - Absolute path "C:\\Fonts\\MyFont.ttf": Uses the specified file
font_path = ""
# Font size in pixels (32.0 recommended for 1080p, 64.0 for 4K)
font_size = 32.0
# Background color and opacity
background_color = "#141414"
background_opacity = 0.3
# Text colors
text_color = "#FFFFFF"
text_disabled_color = "#808080"
# Window border
show_border = false
border_color = "#404040"

[keybindings]
toggle_ui = "f9"
"""


def _get_top_dir(zip_path: Path) -> str | None:
    """Detect the top-level directory name inside a zip file.

    Returns the common top-level directory if all entries share one,
    or None if there's no common prefix.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if not names:
            return None
        # Get unique first path components
        top_dirs = {n.split("/")[0] for n in names if "/" in n}
        if len(top_dirs) == 1:
            return top_dirs.pop()
    return None


def generate_seed_pack_on_demand(participant: Participant, race: Race) -> Path:
    """Generate a personalized seed pack for a participant on-the-fly.

    Copies the base seed zip to a temp file and injects the per-participant
    TOML config. Caller is responsible for deleting the temp file after use.

    Args:
        participant: The participant to generate the pack for
        race: The race with seed information

    Returns:
        Path to the temporary zip file

    Raises:
        ValueError: If race has no seed assigned
        FileNotFoundError: If seed zip doesn't exist
    """
    if not race.seed:
        raise ValueError("Race has no seed assigned")

    seed_zip = Path(race.seed.folder_path)
    if not seed_zip.exists():
        raise FileNotFoundError(f"Seed zip not found: {seed_zip}")

    # Copy to temp file
    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".zip")
    temp_path = Path(temp_path_str)
    try:
        os.close(temp_fd)
        shutil.copy2(seed_zip, temp_path)

        # Detect top-level directory in the zip
        top_dir = _get_top_dir(temp_path)

        # Generate config
        config_content = generate_player_config(participant, race)

        # Inject config into the zip
        config_path = f"{top_dir}/lib/speedfog_race.toml" if top_dir else "lib/speedfog_race.toml"
        with zipfile.ZipFile(temp_path, "a") as zf:
            zf.writestr(config_path, config_content)

        logger.debug(
            f"Generated on-demand seed pack for {participant.user.twitch_username} at {temp_path}"
        )
        return temp_path

    except Exception:
        # Clean up on failure
        temp_path.unlink(missing_ok=True)
        raise
