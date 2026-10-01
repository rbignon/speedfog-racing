#!/usr/bin/env python3
"""Create and open an event's qualifier seeds.

Two commands, both talking to the API with an admin's web session token taken
from the SPEEDFOG_TOKEN environment variable (the ``speedfog_token`` entry of
the browser's localStorage).

``create`` gives every qualifier slot still empty its race, named "<EVENT>
QUALIFIER - <MODE> - SEED <N>" (upper case): the mode's pool, private, run by
the token's account racing in it too, registration closed, late join and
automatic end both the length of the qualifier window. A slot already taken is left as it
is, so a rerun fills the slots a failed run left empty. It is refused once
the qualifier has opened: a race created then would still last the whole
window and close past the cut. The creation is tried once, since a retry
after a lost answer would create a second race, and a race that may exist
without its slot is named so it can be looked for in the admin Races tab
before a rerun; the attach, which can be sent twice, is tried again.

``start`` opens them at ``starts_at``, to the second. The races wait in setup
with registration closed, so that their seeds can be released early and
checked from a participant account without a race id that gets around
leading anyone to a pack. ``start`` opens registration (100 places, the
server's cap), releases the seeds still withheld (a re-roll withdraws them),
then starts every race so that its ``started_at`` lands on the opening. The
server sets ``started_at`` to the start call plus its countdown
(``countdown_seconds``, 10 by default), so the start calls leave that long
before the opening. A race closes ``race_duration_minutes`` after its
``started_at``, so every seed then closes on the cut too; started by hand one
after the other, the last ones would close minutes after it.

A race already running is left alone, so a rerun of ``start`` is harmless. At
launch it prints what it found per slot and flags what needs a look: a slot
with no race, a race neither in setup nor running, a race still holding a
participant other than its organizer (a check account has to be removed
first), a race whose duration does not end it at the cut or whose late join
differs from it, a public race, and a race whose registration is already open. It reads the
state again shortly before the start calls (falling back on the launch's
reading when that fails or lingers), prints it, then opens registration and
releases the seeds. A race whose registration could not be opened stays in
setup, since a started race's registration can no longer be changed. Calls
are tried again on a network error, a server error, a conflict or the rate
limit, and a start that still reads as failed is checked against the race's
own state before it is reported. The exit code is 1 when a race could not be
started or started with a participant other than its organizer still
registered. Logging out of the site replaces the token, so stay logged in
until the opening. The machine's clock decides when the calls leave: run it
on the server itself or on a machine synced over NTP, and keep it awake until
the opening.

Usage (each command also runs with --dry-run, which only prints):
    cd server && SPEEDFOG_TOKEN=... uv run python ../tools/qualifier.py \\
        create --api https://speedfog.racing --slug season-one
    cd server && SPEEDFOG_TOKEN=... uv run python ../tools/qualifier.py \\
        start --api https://speedfog.racing --slug season-one

``start --now`` sends the calls right away instead of waiting for the
opening, for a start that has to be redone after the opening. Before the
opening it is refused unless --before-opening is given too, for a trial on a
local server: on the real event it would open every seed early.
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
# The longest race name the server takes.
NAME_MAX = 200
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


def guests(race: dict[str, Any]) -> int:
    """Participants other than the organizer, who races their own seeds.

    The previews stop at five; the organizer is counted out only when they
    show there, which holds for the few participants a race in setup has.
    """
    organizer = race["organizer"]["id"]
    listed = sum(1 for p in race["participant_previews"] if p["id"] == organizer)
    return int(race["participant_count"]) - listed


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
            if extra := guests(race):
                names = ", ".join(
                    p["twitch_username"]
                    for p in race["participant_previews"]
                    if p["id"] != race["organizer"]["id"]
                )
                notes.append(f"{extra} participant(s) registered: {names}")
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
    attempts: int = ATTEMPTS,
) -> httpx.Response:
    """A call tried again, up to ``attempts`` times, on what a retry can
    fix: the network, a server error and a conflict (a concurrent edit). The
    rate limit refuses a call before the endpoint runs, so a 429 is tried
    again up to ``ATTEMPTS`` times whatever ``attempts`` says."""
    for attempt in range(1, ATTEMPTS + 1):
        delay = 0.5
        try:
            response = await client.request(method, path, json=body)
        except httpx.TransportError as exc:
            if attempt >= attempts:
                raise ApiError(f"{method} {path}: {exc!r}") from exc
        else:
            if response.status_code == 429:
                if attempt == ATTEMPTS:
                    return response
                try:
                    delay = min(float(response.headers.get("Retry-After", "1")), 5.0)
                except ValueError:
                    delay = 1.0
            elif response.status_code == 409 or response.status_code >= 500:
                if attempt >= attempts:
                    return response
            else:
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


async def start_race(
    client: httpx.AsyncClient, race: dict[str, Any]
) -> tuple[bool, str]:
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


def api_client(
    api: str, token: str, transport: httpx.AsyncBaseTransport | None
) -> httpx.AsyncClient:
    """``transport`` lets a test drive the app in process."""
    headers = {"Authorization": f"Bearer {token}"}
    return httpx.AsyncClient(
        base_url=api.rstrip("/"), headers=headers, timeout=15, transport=transport
    )


def window_minutes(detail: dict[str, Any]) -> int:
    """The qualifier window in whole minutes, the unit of a race's durations."""
    window = parse_time(detail["qualifier_ends_at"]) - parse_time(detail["starts_at"])
    seconds = window.total_seconds()
    if seconds <= 0 or seconds % 60:
        raise ValueError(f"a qualifier window of {seconds:g} s is no whole minutes")
    return int(seconds // 60)


async def create_race(
    client: httpx.AsyncClient,
    event_id: str,
    slot: str,
    name: str,
    pool: str,
    minutes: int,
) -> tuple[bool, str]:
    """Create the slot's race, then attach it: ``(True, name)`` or ``(False,
    what failed)``. The creation is tried once, since a retry after a lost
    answer would create a second race; the attach can be sent twice."""
    body = {
        "name": name,
        "pool_name": pool,
        "organizer_participates": True,
        "is_public": False,
        "open_registration": False,
        "late_join_window_minutes": minutes,
        "race_duration_minutes": minutes,
    }
    race_id: str | None = None
    try:
        response = await call(client, "POST", "/api/races", body, attempts=1)
        if response.is_error:
            return False, f"create: {response.status_code} {error_detail(response)}"
        race_id = str(response.json()["id"])
        link = {"event_id": event_id, "slot": slot}
        path = f"/api/admin/races/{race_id}/event"
        response = await call(client, "POST", path, link)
    except ApiError as exc:
        if race_id is None:
            return False, f"{exc}; {name} may exist, look for it before a rerun"
        return False, f"{exc}; {name} ({race_id}) created, its attachment unknown"
    if response.is_error:
        failure = f"attach: {response.status_code} {error_detail(response)}"
        return False, f"{failure}; {name} ({race_id}) created but not attached"
    return True, name


async def run_create(
    api: str,
    slug: str,
    token: str,
    dry_run: bool,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Create and attach the race of every empty qualifier slot."""
    async with api_client(api, token, transport) as client:
        try:
            detail = await get_json(client, f"/api/events/{slug}")
            events = await get_json(client, "/api/admin/events")
        except ApiError as exc:
            print(f"Cannot read the event: {exc}")
            return 1
        event = next((e for e in events if e["slug"] == slug), None)
        if event is None:
            print(f"No event {slug!r} in the admin list")
            return 1
        if datetime.now(UTC) >= parse_time(detail["starts_at"]):
            print(
                "The qualifier has opened: a race created now would still last the"
                " whole window and close past the cut."
            )
            return 1
        try:
            minutes = window_minutes(detail)
        except ValueError as exc:
            print(f"Cannot size the races: {exc}")
            return 1
        print(f"{detail['name']}: races of {minutes} min")
        failed = False
        for mode in detail["modes"]:
            for index in range(1, detail["seeds_per_mode"] + 1):
                slot = f"qualifier:{mode['key']}:{index}"
                name = f"{detail['name']} qualifier - {mode['label']} - Seed {index}".upper()
                if slot in event["attached"]:
                    print(f"  {slot:32s} taken, left as is")
                    continue
                if len(name) > NAME_MAX:
                    print(
                        f"  {slot:32s} FAILED  {name!r} is over {NAME_MAX} characters"
                    )
                    failed = True
                    continue
                if dry_run:
                    print(f"  {slot:32s} to create  {name}")
                    continue
                ok, text = await create_race(
                    client, str(event["id"]), slot, name, mode["key"], minutes
                )
                print(f"  {slot:32s} {'created' if ok else 'FAILED'}  {text}")
                failed = failed or not ok
    return 1 if failed else 0


async def run_start(
    api: str,
    slug: str,
    token: str,
    dry_run: bool,
    now: bool,
    countdown: int,
    before_opening: bool = False,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Open registration, release and start every qualifier race at the
    opening."""
    async with api_client(api, token, transport) as client:
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
        results = await asyncio.gather(*(start_race(client, race) for _, race in ready))

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
    crowded = [slot for slot, race in ready if guests(race)]
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
        description="Create and open an event's qualifier seeds."
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--api", required=True, help="site root, e.g. https://speedfog.racing"
    )
    common.add_argument("--slug", required=True, help="event slug")
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="print the slots and what would be done, then stop",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "create", parents=[common], help="create the races of the empty slots"
    )
    start = commands.add_parser(
        "start", parents=[common], help="open the races at the opening"
    )
    start.add_argument(
        "--now",
        action="store_true",
        help="send the calls right away instead of at the opening",
    )
    start.add_argument(
        "--before-opening",
        action="store_true",
        help="let --now run before the opening (a trial on a local server)",
    )
    start.add_argument(
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
    if args.command == "create":
        code = asyncio.run(run_create(args.api, args.slug, token, args.dry_run))
    else:
        code = asyncio.run(
            run_start(
                args.api,
                args.slug,
                token,
                args.dry_run,
                args.now,
                args.countdown,
                before_opening=args.before_opening,
            )
        )
    sys.exit(code)


if __name__ == "__main__":
    main()
