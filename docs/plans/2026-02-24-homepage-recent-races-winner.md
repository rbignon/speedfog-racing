# Homepage Recent Races & Winner Display

**Date:** 2026-02-24
**Status:** Approved

## Goal

1. Show the 2 most recent finished races on the homepage
2. Display the winner on finished race cards (homepage and /races)

## Design

### Server: `ParticipantPreview` schema

Replace `UserResponse` in `participant_previews` with a new `ParticipantPreview` type:

```python
class ParticipantPreview(UserResponse):
    placement: int | None = None
```

- `placement` is `None` for setup/running races, and for participants who didn't finish
- For **finished races**: return **all** participants, sorted by placement (finished participants sorted by `igt_ms` ASC get placement 1..N, then non-finished participants with `placement=None`)
- For **setup/running races**: keep current behavior (first 5 by inscription order, no placement)

Changes:

- `schemas.py`: add `ParticipantPreview`, update `RaceResponse.participant_previews` type
- `helpers.py`: update `race_response()` to compute placement and sort for finished races

### Frontend: Type update

- `api.ts`: update `User` type in `participant_previews` to include `placement?: number | null`
  - Or create a `ParticipantPreview` interface extending `User`

### Frontend: RaceCard winner row

For finished races where `participant_previews[0]?.placement === 1`:

- Show a winner line between avatar row and meta row
- Display: trophy icon + winner name + avatar (small, 18px)
- Style: green (success color), subtle

### Frontend: Homepage "Recent Results" section

- Add a fetch for `fetchRacesPaginated('finished', 0, 2)` in homepage `onMount`
- New section "Recent Results" below live/upcoming races
- Show 2 race cards max
- Link "See all results" pointing to `/races`

## Non-goals

- No IGT on the race card (available on race detail)
- No top 3 display (but placement data is available for future use)
- No changes to the /races page structure (finished races already listed there)
