"""Race management API routes."""

from uuid import UUID

from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def create_race() -> dict:
    """Create a new race.

    TODO: Implement in Step 3.
    """
    return {"message": "TODO: Create race"}


@router.get("")
async def list_races() -> dict:
    """List races.

    TODO: Implement in Step 3.
    """
    return {"races": []}


@router.get("/{race_id}")
async def get_race(race_id: UUID) -> dict:
    """Get race details.

    TODO: Implement in Step 3.
    """
    return {"message": "TODO: Get race", "race_id": str(race_id)}


@router.post("/{race_id}/participants")
async def add_participant(race_id: UUID) -> dict:
    """Add a participant to a race.

    TODO: Implement in Step 3.
    """
    return {"message": "TODO: Add participant", "race_id": str(race_id)}


@router.delete("/{race_id}/participants/{participant_id}")
async def remove_participant(race_id: UUID, participant_id: UUID) -> dict:
    """Remove a participant from a race.

    TODO: Implement in Step 3.
    """
    return {"message": "TODO: Remove participant"}


@router.post("/{race_id}/generate-zips")
async def generate_zips(race_id: UUID) -> dict:
    """Generate personalized zips for all participants.

    TODO: Implement in Step 6.
    """
    return {"message": "TODO: Generate zips"}


@router.get("/{race_id}/download/{mod_token}")
async def download_zip(race_id: UUID, mod_token: str) -> dict:
    """Download personalized zip for a participant.

    TODO: Implement in Step 6.
    """
    return {"message": "TODO: Download zip"}


@router.post("/{race_id}/start")
async def start_race(race_id: UUID) -> dict:
    """Start the race countdown.

    TODO: Implement in Step 3.
    """
    return {"message": "TODO: Start race"}
