#!/usr/bin/env python3
"""Open an event's qualifier seeds at the opening, to the second.

The qualifier races wait in setup with registration closed, so that their
seeds can be released early and checked from a participant account without a
race id that gets around leading anyone to a pack. This script turns them into
open seeds at ``starts_at``: it opens registration (100 places, the server's
cap), releases the seeds still withheld (a re-roll withdraws them), then
starts every race so that its ``started_at`` lands on the opening. The server
sets ``started_at`` to the start call plus its countdown (``countdown_seconds``,
10 by default), so the start calls leave that long before the opening. A race
closes ``race_duration_minutes`` after its ``started_at``, so every seed then
closes on the cut too; started by hand one after the other, the last ones
would close minutes after it.

A race already running is left alone, so a rerun is harmless. At launch the
script prints what it found per slot and flags what needs a look: a slot with
no race, a race neither in setup nor running, a race still holding a
participant (the check account has to be removed first), a race whose
duration does not end it at the cut or whose late join differs from it, a
public race, and a race whose registration is already open. It reads the
state again shortly before the start calls (falling back on the launch's
reading when that fails or lingers), prints it, then opens registration and
releases the seeds. A race whose registration could not be opened stays in
setup, since a started race's registration can no longer be changed. Calls
are tried again on a network error, a server error, a conflict or the rate
limit, and a start that still reads as failed is checked against the race's
own state before it is reported. The exit code is 1 when a race could not be
started or started with a participant still registered.

It talks to the API with an admin's web session token, taken from the
SPEEDFOG_TOKEN environment variable (the ``speedfog_token`` entry of the
browser's localStorage). Logging out of the site replaces that token, so stay
logged in until the opening. The machine's clock decides when the calls
leave: run it on the server itself or on a machine synced over NTP, and keep
it awake until the opening.

Usage:
    cd server && SPEEDFOG_TOKEN=... uv run python ../tools/start_qualifier.py \\
        --api https://speedfog.racing --slug season-one --dry-run
    cd server && SPEEDFOG_TOKEN=... uv run python ../tools/start_qualifier.py \\
        --api https://speedfog.racing --slug season-one

--now sends the calls right away instead of waiting for the opening, for a
start that has to be redone after the opening. Before the opening it is
refused unless --before-opening is given too, for a trial on a local server:
on the real event it would open every seed early.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

# How long before the start calls the state is read again, registration
# opened and the seeds released.
REFRESH_LEAD = timedelta(seconds=20)
# Tries per call when the failure is one a retry can fix.
ATTEMPTS = 3
# Places of an open registration: the server's cap.
PLACES = 100
# The server's answer to a release of seeds already out.
ALREADY_RELEASED = "Seeds are already released"


class ApiError(Exception):
    """A call that still failed after its tries."""


@dataclass
class SlotPlan:
    """One qualifier slot: its race, whether to start it, what to look at."""

    slot: str
    race: dict[str, Any] | None
    start: bool
    notes: list[str] = field(default_factory=list)


def parse_time(value: str) -> datetime:
    """An API instant, a naive one read as UTC (SQLite drops the offset)."""
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def local(moment: datetime) -> str:
    return f"{moment.astimezone():%a %d %b %Y %H:%M:%S %Z}"


def plan_slots(
    detail: dict[str, Any], attached: dict[str, str], races: dict[str, dict[str, Any]]
) -> list[SlotPlan]:
    """What to do with each qualifier slot of the event.

    ``detail`` is the public event detail (modes, seeds per mode, window),
    ``attached`` the admin map of slot to race id, ``races`` the admin
    in-flight races (setup and running) by id.
    """
    window = parse_time(detail["qualifier_ends_at"]) - parse_time(detail["starts_at"])
    plans: list[SlotPlan] = []
    for mode in detail["modes"]:
        for index in range(1, detail["seeds_per_mode"] + 1):
            slot = f"qualifier:{mode['key']}:{index}"
            race_id = attached.get(slot)
            if race_id is None:
                plans.append(SlotPlan(slot, None, False, ["no race attached"]))
                continue
            race = races.get(race_id)
            if race is None:
                note = f"race {race_id} is neither in setup nor running"
                plans.append(SlotPlan(slot, None, False, [note]))
                continue
            if race["status"] != "setup":
                plans.append(
                    SlotPlan(slot, race, False, ["already running, left alone"])
                )
                continue
            notes: list[str] = []
            if race["participant_count"]:
                names = ", ".join(
                    p["twitch_username"] for p in race["participant_previews"]
                )
                notes.append(
                    f"{race['participant_count']} participant(s) registered: {names}"
                )
            duration = race["race_duration_minutes"]
            if duration is None:
                notes.append("no automatic end")
            elif timedelta(minutes=duration) != window:
                minutes = window.total_seconds() / 60
                notes.append(
                    f"lasts {duration} min, the qualifier window is {minutes:g} min"
                )
            if duration is not None and race["late_join_window_minutes"] != duration:
                late = race["late_join_window_minutes"]
                notes.append(f"late join {late} min, duration {duration} min")
            if race["is_public"]:
                notes.append("public: announced on Discord at the start")
            if race["open_registration"]:
                notes.append(
                    "registration already open: anyone reaching the race can join"
                )
            plans.append(SlotPlan(slot, race, True, notes))
    return plans


def report(plans: list[SlotPlan]) -> None:
    for plan in plans:
        line = f"  {plan.slot:32s} {'start' if plan.start else 'skip':5s}"
        if plan.race is not None:
            line += f"  {plan.race['name']}"
        if plan.start and plan.race is not None:
            released = plan.race["seeds_released_at"] is not None
            line += " (seeds out)" if released else " (seeds released at the opening)"
        print(line)
        for note in plan.notes:
            print(f"      ! {note}")


def error_detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> httpx.Response:
    """A call tried again on what a retry can fix: the network, a server
    error, a conflict (a concurrent edit) and the rate limit."""
    for attempt in range(1, ATTEMPTS + 1):
        delay = 0.5
        try:
            response = await client.request(method, path, json=body)
        except httpx.TransportError as exc:
            if attempt == ATTEMPTS:
                raise ApiError(f"{method} {path}: {exc!r}") from exc
        else:
            if response.status_code == 429:
                try:
                    delay = min(float(response.headers.get("Retry-After", "1")), 5.0)
                except ValueError:
                    delay = 1.0
            elif response.status_code != 409 and response.status_code < 500:
                return response
            if attempt == ATTEMPTS:
                return response
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def get_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await call(client, "GET", path)
    if response.is_error:
        raise ApiError(f"GET {path}: {response.status_code} {error_detail(response)}")
    return response.json()


async def load_plans(
    client: httpx.AsyncClient, slug: str, detail: dict[str, Any]
) -> list[SlotPlan]:
    events = await get_json(client, "/api/admin/events")
    event = next((e for e in events if e["slug"] == slug), None)
    if event is None:
        raise ApiError(f"no event {slug!r} in the admin list")
    races = {r["id"]: r for r in (await get_json(client, "/api/admin/races"))["races"]}
    return plan_slots(detail, event["attached"], races)


async def prepare(
    client: httpx.AsyncClient, race: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Open registration where needed and release the seeds: whether the race
    can start (its registration is open), and what failed. The release goes
    out whatever the plan says, since a re-roll after the last reading
    withdraws it; a release already out is no failure."""
    base = f"/api/races/{race['id']}"
    problems: list[str] = []
    registration_open = race["open_registration"] and race["max_participants"] == PLACES
    try:
        if not registration_open:
            body = {"open_registration": True, "max_participants": PLACES}
            response = await call(client, "PATCH", base, body)
            if response.is_error:
                problems.append(
                    f"registration: {response.status_code} {error_detail(response)}"
                )
            else:
                registration_open = True
        response = await call(client, "POST", f"{base}/release-seeds")
        if response.is_error and error_detail(response) != ALREADY_RELEASED:
            problems.append(f"release: {response.status_code} {error_detail(response)}")
    except ApiError as exc:
        problems.append(str(exc))
    return registration_open, problems


async def start(client: httpx.AsyncClient, race: dict[str, Any]) -> tuple[bool, str]:
    """Start the race: ``(True, started_at)`` or ``(False, what failed)``."""
    base = f"/api/races/{race['id']}"
    try:
        response = await call(client, "POST", f"{base}/start")
        if not response.is_error:
            return True, str(response.json()["started_at"])
        failure = f"start: {response.status_code} {error_detail(response)}"
    except ApiError as exc:
        failure = str(exc)
    # A try whose answer was lost may have started the race, and the next one
    # then reads as a failure: the race's own state settles it.
    try:
        state = await get_json(client, base)
    except ApiError:
        return False, failure
    if state["status"] == "running":
        return True, str(state["started_at"])
    return False, failure


async def sleep_until(moment: datetime) -> None:
    while (left := (moment - datetime.now(UTC)).total_seconds()) > 0:
        await asyncio.sleep(min(left, 30))


async def run(
    api: str,
    slug: str,
    token: str,
    dry_run: bool,
    now: bool,
    countdown: int,
    before_opening: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """The whole run; ``transport`` lets a test drive the app in process."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(
        base_url=api.rstrip("/"), headers=headers, timeout=15, transport=transport
    ) as client:
        try:
            detail = await get_json(client, f"/api/events/{slug}")
            plans = await load_plans(client, slug, detail)
        except ApiError as exc:
            print(f"Cannot read the event: {exc}")
            return 1
        opening = parse_time(detail["starts_at"])
        print(f"{detail['name']}: opens {local(opening)}")
        report(plans)
        due = opening - timedelta(seconds=countdown)
        late = due < datetime.now(UTC) - timedelta(seconds=1)
        if late and not now:
            print(
                f"The start calls were due at {local(due)}: --now starts the races right away."
            )
        if dry_run or (late and not now):
            return 0 if dry_run else 1
        if now and datetime.now(UTC) < due - REFRESH_LEAD and not before_opening:
            print(
                "The opening is still ahead and --now would open every seed early:"
                " leave --now out to wait for it (--before-opening forces it, for a trial)."
            )
            return 1

        fire_at = datetime.now(UTC) if now else due
        if not now:
            print(f"Start calls at {local(fire_at)}, {countdown} s before the opening.")
        await sleep_until(fire_at - REFRESH_LEAD)
        try:
            # Bounded, so that a server slow to answer cannot push the start
            # calls past their time.
            plans = await asyncio.wait_for(
                load_plans(client, slug, detail), REFRESH_LEAD.total_seconds() / 2
            )
            print(f"State at {local(datetime.now(UTC))}:")
            report(plans)
        except (ApiError, TimeoutError) as exc:
            reason = str(exc) or "no answer in time"
            print(
                f"Cannot read the state again ({reason}): going on with the launch's reading."
            )

        to_start = [
            (plan.slot, plan.race) for plan in plans if plan.start and plan.race
        ]
        prepared = await asyncio.gather(
            *(prepare(client, race) for _, race in to_start)
        )
        ready: list[tuple[str, dict[str, Any]]] = []
        for (slot, race), (can_start, problems) in zip(to_start, prepared, strict=True):
            for problem in problems:
                print(f"  {slot:32s} ! {problem}")
            if can_start:
                ready.append((slot, race))
            else:
                print(f"  {slot:32s} left in setup: its registration is still closed")
        await sleep_until(fire_at)
        results = await asyncio.gather(*(start(client, race) for _, race in ready))

    for (slot, _), (ok, text) in zip(ready, results, strict=True):
        if ok:
            started = parse_time(text)
            offset = (started - opening).total_seconds()
            print(
                f"  {slot:32s} started {local(started)} ({offset:+.1f} s from the opening)"
            )
        else:
            print(f"  {slot:32s} FAILED {text}")
    left_alone = [
        plan.slot for plan in plans if plan.race is not None and not plan.start
    ]
    missing = [plan.slot for plan in plans if plan.race is None]
    # Past the start a participant can no longer be removed: they sit on the
    # seed's card all week.
    crowded = [slot for slot, race in ready if race["participant_count"]]
    if left_alone:
        print(f"Left alone, already running: {', '.join(left_alone)}")
    if missing:
        print(f"No race to start: {', '.join(missing)}")
    if crowded:
        print(f"Started with a participant still registered: {', '.join(crowded)}")
    started_all = len(ready) == len(to_start) and all(ok for ok, _ in results)
    return 0 if started_all and not crowded else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open an event's qualifier seeds at the opening, to the second."
    )
    parser.add_argument(
        "--api", required=True, help="site root, e.g. https://speedfog.racing"
    )
    parser.add_argument("--slug", required=True, help="event slug")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the slots and what would be done, then stop",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="send the calls right away instead of at the opening",
    )
    parser.add_argument(
        "--before-opening",
        action="store_true",
        help="let --now run before the opening (a trial on a local server)",
    )
    parser.add_argument(
        "--countdown",
        type=int,
        default=10,
        help="the server's countdown_seconds (default: 10)",
    )
    args = parser.parse_args()
    token = os.environ.get("SPEEDFOG_TOKEN")
    if not token:
        sys.exit(
            "SPEEDFOG_TOKEN is not set (the speedfog_token entry of the site's localStorage)"
        )
    sys.exit(
        asyncio.run(
            run(
                args.api,
                args.slug,
                token,
                args.dry_run,
                args.now,
                args.countdown,
                before_opening=args.before_opening,
            )
        )
    )


if __name__ == "__main__":
    main()
