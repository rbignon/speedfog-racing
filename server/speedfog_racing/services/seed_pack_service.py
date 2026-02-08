"""Seed pack generation service for race participants."""

import logging
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, Race

logger = logging.getLogger(__name__)


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
font_size = 16

[keybindings]
toggle_ui = "f9"
"""


def _copy_seed_contents(seed_folder: Path, dest_folder: Path) -> None:
    """Copy seed folder contents to destination.

    Args:
        seed_folder: Source seed folder path
        dest_folder: Destination folder path
    """
    for item in seed_folder.iterdir():
        dest_path = dest_folder / item.name
        if item.is_dir():
            shutil.copytree(item, dest_path)
        else:
            shutil.copy2(item, dest_path)


def generate_participant_seed_pack(
    participant: Participant,
    race: Race,
    output_dir: Path,
) -> Path:
    """Generate a personalized seed pack for a single participant.

    Args:
        participant: The participant to generate seed pack for
        race: The race with seed information
        output_dir: Directory to write the seed pack to

    Returns:
        Path to the generated seed pack file

    Raises:
        FileNotFoundError: If seed folder doesn't exist
    """
    if not race.seed:
        raise ValueError("Race has no seed assigned")

    seed_folder = Path(race.seed.folder_path)
    if not seed_folder.exists():
        raise FileNotFoundError(f"Seed folder not found: {seed_folder}")

    # Create temp directory for building the seed pack
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        player_dir = temp_path / f"speedfog_{race.seed.seed_number}"
        player_dir.mkdir()

        # Copy seed contents
        _copy_seed_contents(seed_folder, player_dir)

        # Generate and write config file next to the DLL in lib/
        config_content = generate_player_config(participant, race)
        config_path = player_dir / "lib" / "speedfog_race.toml"
        config_path.write_text(config_content)

        # Create zip file
        pack_name = f"{participant.user.twitch_username}"
        seed_pack_path = output_dir / f"{pack_name}.zip"

        # Remove existing seed pack if present
        if seed_pack_path.exists():
            seed_pack_path.unlink()

        # Create the zip archive
        shutil.make_archive(
            str(output_dir / pack_name),
            "zip",
            temp_path,
            player_dir.name,
        )

        logger.debug(
            f"Generated seed pack for {participant.user.twitch_username} at {seed_pack_path}"
        )

    return seed_pack_path


async def generate_race_seed_packs(
    db: AsyncSession,
    race: Race,
) -> dict[UUID, Path]:
    """Generate personalized seed packs for all participants in a race.

    Args:
        db: Database session
        race: Race to generate seed packs for (must have seed and participants loaded)

    Returns:
        Dict mapping participant_id -> path to generated seed pack

    Raises:
        ValueError: If race has no seed or no participants
    """
    if not race.seed:
        raise ValueError("Race has no seed assigned")

    if not race.participants:
        raise ValueError("Race has no participants")

    # Create output directory for this race
    output_dir = Path(settings.seed_packs_output_dir) / str(race.id)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[UUID, Path] = {}

    for participant in race.participants:
        try:
            seed_pack_path = generate_participant_seed_pack(participant, race, output_dir)
            results[participant.id] = seed_pack_path
            participant.has_seed_pack = True
            logger.info(
                f"Generated seed pack for participant {participant.id} "
                f"({participant.user.twitch_username})"
            )
        except Exception as e:
            logger.error(f"Failed to generate seed pack for participant {participant.id}: {e}")
            raise

    await db.flush()
    return results


async def get_participant_seed_pack_path(
    race_id: UUID,
    mod_token: str,
    db: AsyncSession,
) -> tuple[Path, Participant] | None:
    """Get the seed pack path for a participant by mod_token.

    Args:
        race_id: The race ID
        mod_token: The participant's mod token
        db: Database session

    Returns:
        Tuple of (seed_pack_path, participant) if found, None otherwise
    """
    result = await db.execute(
        select(Participant)
        .where(Participant.race_id == race_id, Participant.mod_token == mod_token)
        .options(selectinload(Participant.user))
    )
    participant = result.scalar_one_or_none()

    if not participant:
        return None

    seed_pack_path = (
        Path(settings.seed_packs_output_dir)
        / str(race_id)
        / f"{participant.user.twitch_username}.zip"
    )

    if not seed_pack_path.exists():
        return None

    return seed_pack_path, participant
