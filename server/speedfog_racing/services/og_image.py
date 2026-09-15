"""OG image rendering pipeline: Jinja SVG templates → PNG bytes."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import logging
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import resvg_py
from jinja2 import Environment, FileSystemLoader, select_autoescape

from speedfog_racing.models import Event, ParticipantStatus, Race, RaceStatus, User
from speedfog_racing.schemas import EVENT_PHASES, EventConfig
from speedfog_racing.services.event_service import (
    JOINABLE_PHASES,
    UNDECIDED,
    Slot,
    compute_ladder,
    compute_phase,
    compute_qualified,
    compute_stage_results,
    current_stage_key,
    event_window,
    final_field,
    newcomer_flags,
    parse_slot,
)
from speedfog_racing.services.pool_service import format_pool_display_name

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    # select_autoescape matches filename suffixes: ".svg" alone would miss
    # our "*.svg.j2" template names and silently disable escaping.
    autoescape=select_autoescape(["svg.j2", "svg", "xml"]),
)

_TEMPLATE_BY_KIND = {
    "setup": "og/setup.svg.j2",
    "running": "og/running.svg.j2",
    "finished": "og/finished.svg.j2",
    "daily": "og/daily.svg.j2",
    "event_upcoming": "og/event_upcoming.svg.j2",
    "event_entrants": "og/event_entrants.svg.j2",
    "event_stage": "og/event_stage.svg.j2",
    "event_winner": "og/event_winner.svg.j2",
}

# Folded into cache filenames so a visual redesign of the templates, or a change
# in how they are rasterized, stops serving stale PNGs. Bump on every refresh.
_TEMPLATE_VERSION = 5

_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"


def render_svg(kind: str, ctx: dict[str, Any]) -> str:
    """Render the OG SVG for a given card kind (a race status, or an event shape)."""
    name = _TEMPLATE_BY_KIND[kind]
    template = _env.get_template(name)
    return template.render(**ctx)


def rasterize_svg(svg: str) -> bytes:
    """Rasterize an SVG string to PNG bytes at the SVG's intrinsic size.

    System fonts stay enabled as a fallback for glyphs outside our latin
    subsets (e.g. non-latin Twitch display names).
    """
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, font_dirs=[str(_FONT_DIR)]))


_MAX_RACE_NAME = 28
_MAX_AVATARS = 6


STATUS_LABEL = {
    RaceStatus.SETUP: "Upcoming",
    RaceStatus.RUNNING: "Live",
    RaceStatus.FINISHED: "Finished",
}

ACCENT_COLOR = {
    RaceStatus.SETUP: "#4aae8c",  # verdigris (open)
    RaceStatus.RUNNING: "#dc6a51",  # ember
    RaceStatus.FINISHED: "#7ba2cc",  # steel
}

assert ACCENT_COLOR.keys() == STATUS_LABEL.keys(), (
    "ACCENT_COLOR and STATUS_LABEL must cover the same RaceStatus values"
)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


DAILY_ACCENT_COLOR = "#c8a44e"


def format_daily_date(d: dt.date) -> str:
    """Format a daily date as 'Weekday D Month YYYY' (e.g. 'Monday 27 April 2026')."""
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B %Y')}"


def format_pool(race: Race) -> str:
    """The race's pool as the rest of the site names it, or a card-sized stand-in."""
    if race.seed is None:
        return "Unknown pool"
    return format_pool_display_name(race.seed.pool)


def _build_daily_context(race: Race) -> dict[str, Any]:
    assert race.daily_date is not None
    return {
        "accent_color": DAILY_ACCENT_COLOR,
        "date_label": format_daily_date(race.daily_date),
        "pool_display_name": format_pool(race),
    }


def _format_scheduled(scheduled_at: Any, tz_name: str | None) -> str | None:
    if scheduled_at is None:
        return None
    tz: Any = UTC
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("invalid organizer timezone %r, falling back to UTC", tz_name)
    local = scheduled_at.astimezone(tz)
    offset = local.utcoffset() or dt.timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    if minutes:
        suffix = f"UTC{sign}{hours}:{minutes:02d}"
    elif total_minutes == 0:
        suffix = "UTC"
    else:
        suffix = f"UTC{sign}{hours}"
    return str(local.strftime("%b %d, %H:%M")) + " " + suffix


# resvg trusts the media type declared in a data URI instead of sniffing the
# bytes, and silently draws nothing when the two disagree, so name the format.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF8", "gif"),
    (b"<svg", "svg+xml"),
    (b"<?xml", "svg+xml"),
)


def _image_subtype(image_bytes: bytes) -> str | None:
    """The image/* subtype these bytes announce, or None if they announce none."""
    head = image_bytes.lstrip()
    subtype = next((s for magic, s in _IMAGE_MAGIC if head.startswith(magic)), None)
    if subtype is None and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        subtype = "webp"
    return subtype


def _b64(image_bytes: bytes) -> str:
    return f"data:image/{_image_subtype(image_bytes) or 'png'};base64," + base64.b64encode(
        image_bytes
    ).decode("ascii")


def _previews(race: Race) -> tuple[list[Any], int, Any]:
    """Return (avatar_previews, overflow_count, winner_participant_or_None)."""
    if race.status == RaceStatus.FINISHED:
        finished = sorted(
            (p for p in race.participants if p.status == ParticipantStatus.FINISHED),
            key=lambda p: p.igt_ms,
        )
        non_finished = [p for p in race.participants if p.status != ParticipantStatus.FINISHED]
        ordered = finished + non_finished
        winner_p = finished[0] if finished else None
    else:
        ordered = list(race.participants)
        winner_p = None

    head = ordered[:_MAX_AVATARS]
    overflow = max(0, len(ordered) - _MAX_AVATARS)
    return head, overflow, winner_p


def _participant_count_label(race: Race) -> str:
    n = len(race.participants)
    if race.status == RaceStatus.SETUP and race.max_participants is not None:
        body = f"{n}/{race.max_participants} player"
    else:
        body = f"{n} player"
    if n != 1:
        body += "s"
    return body


AvatarLookup = Callable[[str | None], bytes] | Callable[[str | None], Awaitable[bytes]]


async def _resolve(lookup: AvatarLookup, url: str | None) -> bytes:
    result = lookup(url)
    if hasattr(result, "__await__"):
        return await result
    return result


async def build_context(race: Race, *, avatar_lookup: AvatarLookup) -> dict[str, Any]:
    head, overflow, winner_p = _previews(race)
    participants = []
    for p in head:
        avatar_bytes = await _resolve(avatar_lookup, p.user.twitch_avatar_url)
        participants.append(
            {
                "name": p.user.twitch_display_name or p.user.twitch_username,
                "avatar_b64": _b64(avatar_bytes),
            }
        )
    organizer_avatar = await _resolve(avatar_lookup, race.organizer.twitch_avatar_url)
    winner_dict = None
    if winner_p is not None:
        winner_avatar = await _resolve(avatar_lookup, winner_p.user.twitch_avatar_url)
        winner_dict = {
            "name": winner_p.user.twitch_display_name or winner_p.user.twitch_username,
            "avatar_b64": _b64(winner_avatar),
        }
    return {
        "race_name": _truncate(race.name, _MAX_RACE_NAME),
        "status_label": STATUS_LABEL[race.status],
        "accent_color": ACCENT_COLOR[race.status],
        "pool_name": format_pool(race),
        "participant_count_label": _participant_count_label(race),
        "organizer_name": race.organizer.twitch_display_name or race.organizer.twitch_username,
        "organizer_avatar_b64": _b64(organizer_avatar),
        "participants": participants,
        "overflow_count": overflow,
        "winner": winner_dict,
        "scheduled_label": (
            _format_scheduled(race.scheduled_at, getattr(race.organizer, "timezone", None))
            if race.status == RaceStatus.SETUP
            else None
        ),
    }


def _cache_key(race: Race) -> str:
    if race.status == RaceStatus.FINISHED:
        finishers = sorted(
            (
                (str(p.user_id), p.igt_ms)
                for p in race.participants
                if p.status == ParticipantStatus.FINISHED
            ),
            key=lambda t: t[1],
        )
        snapshot = "F:" + "|".join(f"{uid}@{igt}" for uid, igt in finishers)
    else:
        ids = sorted(str(p.user_id) for p in race.participants)
        scheduled = int(race.scheduled_at.timestamp()) if race.scheduled_at else "none"
        tz = getattr(race.organizer, "timezone", None) or "utc"
        snapshot = (
            race.status.value
            + ":"
            + ",".join(ids)
            + f"|max={race.max_participants}"
            + f"|sched={scheduled}"
            + f"|tz={tz}"
        )
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:8]


async def render_race_og(
    race: Race,
    *,
    cache_dir: Path,
    avatar_lookup: AvatarLookup,
) -> tuple[bytes, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(race)
    cached = cache_dir / f"{race.id}-v{_TEMPLATE_VERSION}-{key}.png"
    if cached.exists():
        return cached.read_bytes(), key
    ctx = await build_context(race, avatar_lookup=avatar_lookup)
    svg = render_svg(race.status.value, ctx)
    png = await asyncio.to_thread(rasterize_svg, svg)
    cached.write_bytes(png)
    return png, key


async def render_daily_og(race: Race, *, cache_dir: Path) -> bytes:
    """Render the OG image for a Daily Seed.

    The cache key is just the daily date: the rendered output is fully
    determined by ``race.daily_date`` and the pool's display name (immutable
    after creation), so there is no need for a hashed key.
    The template version joins the name so redesigns invalidate old renders.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"daily-v{_TEMPLATE_VERSION}-{race.daily_date}.png"
    if cached.exists():
        return cached.read_bytes()
    ctx = _build_daily_context(race)
    svg = render_svg("daily", ctx)
    png = await asyncio.to_thread(rasterize_svg, svg)
    cached.write_bytes(png)
    return png


# --- events -----------------------------------------------------------------

EVENT_STATUS_LABEL = {
    "upcoming": "Upcoming",
    "qualifier": "Qualifier open",
    "cut": "Qualifier closed",
    "playoffs": "Playoffs",
    "finished": "Finished",
}

# The event page's phase signals, with verdigris standing in for the page's grey
# on an announced event: an OG card is a poster, and grey reads as disabled.
EVENT_ACCENT_COLOR = {
    "upcoming": "#4aae8c",  # verdigris
    "qualifier": "#dc6a51",  # ember
    "cut": "#c8a44e",  # brass
    "playoffs": "#dc6a51",  # ember
    "finished": "#7ba2cc",  # steel
}

assert EVENT_ACCENT_COLOR.keys() == EVENT_STATUS_LABEL.keys() == set(EVENT_PHASES), (
    "every phase of EVENT_PHASES needs a label and an accent colour"
)

_MAX_ENTRANTS = 14
# An upcoming card shows who is in only from this many players: below it, the
# opening day is the whole message rather than how few have committed yet.
_MIN_UPCOMING_ENTRANTS = 10
_MAX_FIELD_SEATS = 8
_MAX_EVENT_NAME = 40
_MAX_PARTNER_NAME = 20
_MAX_STAGE_LABEL = 24
# Content width of the card: the 1200px canvas minus the 60px side margins.
_CONTENT_WIDTH = 1080
# The lockup keeps clear of the partner logo sitting at x=1064.
_LOCKUP_WIDTH_WITH_LOGO = 888
# A stage caption sets its label and its date apart by this much.
_CAPTION_GAP = 76


@dataclass(frozen=True)
class EventOgSlot:
    """One seat of a playoff line-up: its runner, or what it still waits on."""

    user: User | None
    label: str


@dataclass(frozen=True)
class EventOgSummary:
    """Everything an event card shows, settled before any avatar is fetched."""

    kind: str
    phase: str
    status_label: str
    accent_color: str
    partner_name: str | None
    event_name: str
    lockup_font_size: int
    logo_url: str | None
    headline_label: str | None
    headline: str | None
    headline_font_size: int
    caption: str | None
    caption_font_size: int
    stage_label: str | None
    stage_date: str | None
    entrants: list[User]
    overflow_count: int
    field: list[EventOgSlot]
    field_overflow_count: int
    field_size: int
    field_gap: int
    winner: User | None
    winner_font_size: int
    player_count_label: str | None
    window_label: str
    cache_key: str


def _display_chars(text: str) -> int:
    """Length in latin-sized glyphs: CJK and other full-width characters take two.

    Our latin subsets do not cover them, so they come from the system fallback
    at roughly one em each, twice what the advance ratios below assume.
    """
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _fitted_size(
    chars: int, *, size: int, floor: int, ratio: float, spacing: float, available: float
) -> int:
    """Step a font down until ``chars`` glyphs fit ``available`` pixels.

    ``ratio`` is the typeface's average advance as a fraction of its size
    (0.6 for Spline Sans Mono, 0.42 for Barlow Condensed in caps).
    """
    while size > floor and chars * (ratio * size + spacing) > available:
        size -= 2
    return size


def _fitting_chars(text: str, budget: int) -> int:
    """How many characters of ``text`` fit a cell ``budget`` latin glyphs wide."""
    if not text:
        return budget
    return max(4, round(budget * len(text) / _display_chars(text)))


def _field_geometry(count: int) -> tuple[int, int]:
    """Avatar size and gap of a line-up, so that any field stays centred and legible."""
    for limit, size, gap in ((2, 112, 56), (4, 96, 44), (6, 84, 30)):
        if count <= limit:
            return size, gap
    return 72, 22


def _event_day(moment: dt.datetime, *, weekday: bool = False) -> str:
    """A calendar day in UTC: "23 September", or "Wednesday 23 September".

    Stage times are evening slots, so the day is all the card shows and the
    viewer's own zone never shifts it.
    """
    day = moment.astimezone(UTC)
    label = f"{day.day} {day.strftime('%B')}"
    return f"{day.strftime('%A')} {label}" if weekday else label


def _event_window_label(starts_at: dt.datetime, ends_at: dt.datetime) -> str:
    start, end = starts_at.astimezone(UTC), ends_at.astimezone(UTC)
    if start.year == end.year:
        return f"{_event_day(start)} - {_event_day(end)} {end.year}"
    return f"{_event_day(start)} {start.year} - {_event_day(end)} {end.year}"


def _entrant_count_label(count: int) -> str | None:
    if not count:
        return None
    return f"{count} player" if count == 1 else f"{count} players"


def summarize_event(
    event: Event, *, now: dt.datetime, finished_before: dict[UUID, int]
) -> EventOgSummary:
    """What the event's card shows at ``now``, resolved the way the event page does.

    ``finished_before`` is the caller's ``count_finished_before`` result: it
    decides who counts as a newcomer, and with that the newcomers' line-up.
    """
    starts_at, qualifier_ends_at, ends_at = event_window(event)
    config = EventConfig.model_validate(event.config)

    attached: list[tuple[Slot, Race]] = []
    for race in event.races:
        if race.event_slot is None:
            continue
        try:
            attached.append((parse_slot(race.event_slot), race))
        except ValueError:
            continue
    mode_keys = config.mode_keys()
    qualifier = sorted(
        ((s, r) for s, r in attached if s.kind == "qualifier" and s.key in mode_keys),
        key=lambda item: (mode_keys.index(item[0].key), item[0].index),
    )
    users = {p.user_id: p.user for race in event.races for p in race.participants}

    final = config.final_stage()
    advance = (final.advance or 0) if final is not None else 0
    results = {
        stage.key: compute_stage_results(
            stage,
            [r for s, r in attached if s.kind == "stage" and s.key == stage.key],
            advance if stage.kind == "semi" else 0,
        )
        for stage in config.stages
    }
    labels = {s.key: s.label for s in config.stages}
    last = config.stages[-1] if config.stages else None
    phase = compute_phase(
        now=now,
        starts_at=starts_at,
        qualifier_ends_at=qualifier_ends_at,
        ends_at=ends_at,
        first_stage_at=config.stages[0].date if config.stages else None,
        last_stage_complete=results[last.key].complete if last is not None else False,
        override=config.phase_override,
    )

    if phase in JOINABLE_PHASES:
        signed_up = [s.user_id for s in event.signups]
        users.update({s.user_id: s.user for s in event.signups})
    else:
        signed_up = []
    ladder = compute_ladder(mode_keys, qualifier, signed_up=signed_up)
    newcomers = newcomer_flags(finished_before, event.newcomer_threshold, users.keys())
    qualified = compute_qualified(ladder, config, newcomers)

    # The ladder already runs best first, then the runners it could not rank;
    # everyone else joined a race without ever scoring and closes the row.
    ranked_ids = {entry.user_id for entry in ladder}
    ordered = [users[entry.user_id] for entry in ladder if entry.user_id in users]
    ordered += sorted(
        (user for user_id, user in users.items() if user_id not in ranked_ids),
        key=lambda u: u.twitch_username,
    )
    entrants = ordered[:_MAX_ENTRANTS]
    overflow_count = max(0, len(ordered) - _MAX_ENTRANTS)
    player_count = len(users)
    if phase == "upcoming" and player_count < _MIN_UPCOMING_ENTRANTS:
        entrants, overflow_count, player_count = [], 0, 0

    winner = None
    if phase == "finished" and final is not None:
        result = results[final.key]
        if result.complete and result.entries:
            winner = users.get(result.entries[0].user_id)
    stage = (
        config.stage(current_stage_key(config, now) or "") if phase in ("cut", "playoffs") else None
    )

    def user_of(user_id: UUID | None) -> User | None:
        return users.get(user_id) if user_id is not None else None

    headline_label = headline = caption = stage_label = stage_date = None
    field: list[EventOgSlot] = []
    if phase == "upcoming":
        kind = "event_upcoming"
        headline_label = "Qualifier opens"
        headline = _event_day(starts_at, weekday=True)
    elif phase == "qualifier":
        kind = "event_entrants"
        caption = f"Qualifier closes on {_event_day(qualifier_ends_at)}"
    elif winner is not None:
        kind = "event_winner"
    elif stage is not None:
        kind = "event_stage"
        stage_label = _truncate(stage.label, _MAX_STAGE_LABEL)
        stage_date = _event_day(stage.date, weekday=True)
        if stage.kind == "final":
            # "Top 2 of Semi B" is the page's phrasing; under an empty ring the
            # card only has room for the stage the runner comes from.
            field = [
                EventOgSlot(user_of(slot.user_id), slot.label.split(" of ", 1)[-1])
                for slot in final_field(stage, results, labels)
            ]
        else:
            field = [
                EventOgSlot(
                    user_of(slot.user_id),
                    f"Seed {slot.seed}" if slot.seed is not None else UNDECIDED,
                )
                for slot in qualified.get(stage.key, [])
            ]
    else:
        # Playoffs with no stage configured, or a window that ran out before a
        # final was ever played: the field and a plain caption are what is left.
        kind = "event_entrants"
        caption = "Event finished" if phase == "finished" else EVENT_STATUS_LABEL[phase]

    field_overflow_count = max(0, len(field) - _MAX_FIELD_SEATS)
    field = field[:_MAX_FIELD_SEATS]
    partner_name = _truncate(event.partner_name, _MAX_PARTNER_NAME) if event.partner_name else None
    event_name = _truncate(event.name, _MAX_EVENT_NAME)
    # What the lockup line will read, to size it and to key the cache on it.
    lockup = f"SpeedFog × {partner_name} {event_name}" if partner_name else event_name
    caption_chars = len(caption or "") + len(stage_label or "") + len(stage_date or "")
    field_size, field_gap = _field_geometry(len(field) + (1 if field_overflow_count else 0))
    window_label = _event_window_label(starts_at, ends_at)
    player_count_label = _entrant_count_label(player_count)

    cache_key = hashlib.sha256(
        "|".join(
            [
                kind,
                phase,
                lockup,
                headline or "",
                caption or "",
                stage_label or "",
                stage_date or "",
                window_label,
                player_count_label or "",
                event.partner_logo_url or "",
                f"+{overflow_count}/{field_overflow_count}",
                *(str(user.id) for user in entrants),
                *(f"{slot.user.id if slot.user else ''}@{slot.label}" for slot in field),
                str(winner.id) if winner is not None else "",
            ]
        ).encode("utf-8")
    ).hexdigest()[:8]

    return EventOgSummary(
        kind=kind,
        phase=phase,
        status_label=EVENT_STATUS_LABEL[phase],
        accent_color=EVENT_ACCENT_COLOR[phase],
        partner_name=partner_name,
        event_name=event_name,
        lockup_font_size=_fitted_size(
            len(lockup),
            size=58,
            floor=40,
            ratio=0.42,
            spacing=2.2,
            available=_LOCKUP_WIDTH_WITH_LOGO if event.partner_logo_url else _CONTENT_WIDTH,
        ),
        logo_url=event.partner_logo_url,
        headline_label=headline_label,
        headline=headline,
        headline_font_size=_fitted_size(
            len(headline or ""),
            size=84,
            floor=60,
            ratio=0.42,
            spacing=2.4,
            available=_CONTENT_WIDTH,
        ),
        caption=caption,
        caption_font_size=_fitted_size(
            caption_chars,
            size=34,
            floor=26,
            ratio=0.6,
            spacing=5,
            available=_CONTENT_WIDTH - (_CAPTION_GAP if stage_label else 0),
        ),
        stage_label=stage_label,
        stage_date=stage_date,
        entrants=entrants,
        overflow_count=overflow_count,
        field=field,
        field_overflow_count=field_overflow_count,
        field_size=field_size,
        field_gap=field_gap,
        winner=winner,
        winner_font_size=_fitted_size(
            _display_chars(winner.twitch_display_name or winner.twitch_username) if winner else 0,
            size=72,
            floor=48,
            ratio=0.42,
            spacing=1.5,
            available=_CONTENT_WIDTH,
        ),
        player_count_label=player_count_label,
        window_label=window_label,
        cache_key=cache_key,
    )


async def build_event_context(
    summary: EventOgSummary, *, avatar_lookup: AvatarLookup, logo_lookup: AvatarLookup
) -> dict[str, Any]:
    entrants = []
    for user in summary.entrants:
        avatar = await _resolve(avatar_lookup, user.twitch_avatar_url)
        entrants.append({"avatar_b64": _b64(avatar)})

    # A name wider than its own cell would run into its neighbour's.
    cell_chars = max(6, int((summary.field_size + summary.field_gap) / 12))
    field = []
    for slot in summary.field:
        seated: bytes | None = None
        if slot.user is not None:
            seated = await _resolve(avatar_lookup, slot.user.twitch_avatar_url)
        name = (slot.user.twitch_display_name or slot.user.twitch_username) if slot.user else None
        field.append(
            {
                "name": _truncate(name, _fitting_chars(name, cell_chars)) if name else None,
                "avatar_b64": _b64(seated) if seated else None,
                "label": _truncate(slot.label, _fitting_chars(slot.label, cell_chars)),
            }
        )

    winner = None
    if summary.winner is not None:
        avatar = await _resolve(avatar_lookup, summary.winner.twitch_avatar_url)
        winner = {
            "name": summary.winner.twitch_display_name or summary.winner.twitch_username,
            "avatar_b64": _b64(avatar),
        }

    logo = await _resolve(logo_lookup, summary.logo_url) if summary.logo_url else b""
    if logo and _image_subtype(logo) is None:
        # A site-relative URL that no longer resolves hands back the SPA shell
        # with a 200; drawing it would put an unreadable smear on the card.
        logger.warning("partner logo at %s is not an image, leaving it out", summary.logo_url)
        logo = b""
    return {
        "accent_color": summary.accent_color,
        "status_label": summary.status_label,
        "partner_name": summary.partner_name,
        "event_name": summary.event_name,
        "lockup_font_size": summary.lockup_font_size,
        "logo_b64": _b64(logo) if logo else None,
        "headline_label": summary.headline_label,
        "headline": summary.headline,
        "headline_font_size": summary.headline_font_size,
        "caption": summary.caption,
        "caption_font_size": summary.caption_font_size,
        "stage_label": summary.stage_label,
        "stage_date": summary.stage_date,
        "entrants": entrants,
        "overflow_count": summary.overflow_count,
        "field": field,
        "field_overflow_count": summary.field_overflow_count,
        "field_size": summary.field_size,
        "field_gap": summary.field_gap,
        "caption_gap": _CAPTION_GAP,
        "winner": winner,
        "winner_font_size": summary.winner_font_size,
        "player_count_label": summary.player_count_label,
        "window_label": summary.window_label,
    }


def event_og_description(summary: EventOgSummary) -> str:
    """The og:description twin of the card: the same phase state, in one line."""
    if summary.kind == "event_upcoming":
        parts = [f"{summary.headline_label} {summary.headline}"]
    elif summary.kind == "event_stage":
        parts = [f"{summary.stage_label} on {summary.stage_date}"]
    elif summary.winner is not None:
        name = summary.winner.twitch_display_name or summary.winner.twitch_username
        parts = [f"Won by {name}"]
    else:
        parts = [summary.caption or summary.status_label]
    if summary.player_count_label:
        parts.append(summary.player_count_label)
    return " · ".join(parts)


async def render_event_og(
    event: Event,
    *,
    now: dt.datetime,
    finished_before: dict[UUID, int],
    cache_dir: Path,
    avatar_lookup: AvatarLookup,
    logo_lookup: AvatarLookup,
) -> bytes:
    """Render (or serve from disk) the OG image of an event at ``now``."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_event(event, now=now, finished_before=finished_before)
    cached = cache_dir / f"event-{event.slug}-v{_TEMPLATE_VERSION}-{summary.cache_key}.png"
    if cached.exists():
        return cached.read_bytes()
    ctx = await build_event_context(summary, avatar_lookup=avatar_lookup, logo_lookup=logo_lookup)
    svg = render_svg(summary.kind, ctx)
    png = await asyncio.to_thread(rasterize_svg, svg)
    cached.write_bytes(png)
    return png
