"""Pure scoring and phase logic of tournament events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from speedfog_racing.models import ParticipantStatus, RaceStatus
from speedfog_racing.schemas import EventConfig
from speedfog_racing.services.event_service import (
    UNDECIDED,
    Slot,
    StageEntry,
    StageResult,
    build_timeline,
    compute_ladder,
    compute_phase,
    compute_qualified,
    compute_stage_results,
    current_stage_key,
    fed_field,
    newcomer_flags,
    next_stage_key,
    parse_slot,
    race_moment,
    resolve_stages,
    score_race,
    signature_weapon,
    stage_dates,
    validate_slot,
)
from speedfog_racing.services.weapons import WEAPONS

MODES = ["standard", "boss_rush"]


def _config(seeds_a=(1, 4), seeds_b=(2, 3), newcomers_size=2) -> EventConfig:
    return EventConfig.model_validate(
        {
            "modes": [{"key": m, "label": m} for m in MODES],
            "seeds_per_mode": 2,
            "announced_at": "2026-09-16T18:00:00Z",
            "stages": [
                {
                    "key": "semi_a",
                    "label": "Semi A",
                    "kind": "semi",
                    "date": "2026-10-04T19:00:00Z",
                    "races": 3,
                    "seeds": list(seeds_a),
                    "advance": 2,
                },
                {
                    "key": "semi_b",
                    "label": "Semi B",
                    "kind": "semi",
                    "date": "2026-10-11T19:00:00Z",
                    "races": 3,
                    "seeds": list(seeds_b),
                    "advance": 2,
                },
                {
                    "key": "newcomers",
                    "label": "Newcomers",
                    "kind": "newcomers",
                    "date": "2026-10-18T19:00:00Z",
                    "races": 2,
                    "size": newcomers_size,
                },
                {
                    "key": "final",
                    "label": "Final",
                    "kind": "final",
                    "date": "2026-10-25T19:00:00Z",
                    "races": 3,
                    "from": ["semi_a", "semi_b"],
                },
            ],
        }
    )


def _participant(user_id: UUID, status: ParticipantStatus, igt_ms: int, layer: int = 5):
    # Two zone entries make the run "qualified" for scoring, as on dailies.
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        status=status,
        igt_ms=igt_ms,
        current_layer=layer,
        zone_history=[{"node_id": "a"}, {"node_id": "b"}],
    )


def _race(participants, status=RaceStatus.FINISHED):
    return SimpleNamespace(status=status, participants=list(participants))


# --- slots ------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, kind, key, index",
    [("qualifier:standard:2", "qualifier", "standard", 2), ("semi_a:3", "stage", "semi_a", 3)],
)
def test_parse_slot(raw, kind, key, index):
    assert parse_slot(raw) == Slot(kind=kind, key=key, index=index)


@pytest.mark.parametrize("raw", ["qualifier:standard", "semi_a:0", "semi_a:x", "a:b:c:d", ""])
def test_parse_slot_rejects_malformed(raw):
    with pytest.raises(ValueError):
        parse_slot(raw)


def test_validate_slot_against_config():
    cfg = _config()
    assert validate_slot(parse_slot("qualifier:standard:2"), cfg) is None
    assert "seeds_per_mode" in (validate_slot(parse_slot("qualifier:standard:3"), cfg) or "")
    assert "unknown mode" in (validate_slot(parse_slot("qualifier:sprint:1"), cfg) or "")
    assert validate_slot(parse_slot("semi_a:3"), cfg) is None
    assert "races" in (validate_slot(parse_slot("semi_a:4"), cfg) or "")
    assert "unknown stage" in (validate_slot(parse_slot("quarter:1"), cfg) or "")


# --- race scores ------------------------------------------------------------


def test_score_race_ranks_finishers_then_dnf_and_marks_provisional():
    a, b, c = uuid4(), uuid4(), uuid4()
    race = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 3_000_000),
            _participant(b, ParticipantStatus.FINISHED, 2_000_000),
            _participant(c, ParticipantStatus.ABANDONED, 500_000, layer=3),
        ],
        status=RaceStatus.RUNNING,
    )
    scores = score_race(race)
    assert scores[b].rank == 1 and scores[b].points == 100
    assert scores[a].rank == 2 and scores[c].rank == 3
    assert scores[c].points >= 1
    assert all(s.provisional for s in scores.values())


def test_score_race_ignores_unqualified_runs():
    a = uuid4()
    p = _participant(a, ParticipantStatus.FINISHED, 1_000_000)
    p.zone_history = [{"node_id": "a"}]
    assert score_race(_race([p])) == {}


def test_score_race_settled_only_leaves_runs_in_progress_out_of_the_field():
    a, b, c = uuid4(), uuid4(), uuid4()
    race = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 3_000_000),
            _participant(b, ParticipantStatus.PLAYING, 500_000, layer=8),
            _participant(c, ParticipantStatus.ABANDONED, 500_000, layer=3),
        ],
        status=RaceStatus.RUNNING,
    )
    # By default a run in progress ranks like a DNF on its depth so far.
    assert set(score_race(race)) == {a, b, c}
    scores = score_race(race, settled_only=True)
    assert set(scores) == {a, c}
    # The field is the settled runs only: 2nd of 2 scores 50, not 3rd of 3.
    assert scores[a].points == 100 and scores[c].rank == 2 and scores[c].points == 50


def test_score_race_ties_share_rank_and_skip_the_next_rank():
    a, b, c = uuid4(), uuid4(), uuid4()
    race = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 1_000_000),
            _participant(b, ParticipantStatus.FINISHED, 1_000_000),
            _participant(c, ParticipantStatus.FINISHED, 2_000_000),
        ]
    )
    scores = score_race(race)
    assert scores[a].rank == 1 and scores[b].rank == 1
    assert scores[a].points == scores[b].points
    assert scores[c].rank == 3


# --- ladder -----------------------------------------------------------------


def test_ladder_takes_best_seed_per_mode_and_requires_every_mode():
    a, b = uuid4(), uuid4()
    std1 = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 60),
            _participant(b, ParticipantStatus.FINISHED, 50),
        ]
    )
    std2 = _race([_participant(a, ParticipantStatus.FINISHED, 40)])
    boss1 = _race([_participant(a, ParticipantStatus.FINISHED, 70)])
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), std1),
            (parse_slot("qualifier:standard:2"), std2),
            (parse_slot("qualifier:boss_rush:1"), boss1),
        ],
    )
    by_user = {e.user_id: e for e in ladder}
    # a: 50 pts (2nd of 2) on std1, 100 on std2 -> best 100; 100 on boss1 -> total 200
    assert by_user[a].mode_points == {"standard": 100, "boss_rush": 100}
    assert by_user[a].counted_slots["standard"] == "qualifier:standard:2"
    assert by_user[a].total == 200 and by_user[a].rank == 1
    # b never played boss_rush: unranked, listed after ranked entries
    assert by_user[b].total is None and by_user[b].rank is None
    assert by_user[b].modes_scored == 1 and by_user[b].partial == 100
    assert ladder[0].user_id == a and ladder[-1].user_id == b


def test_ladder_breaks_total_ties_on_counted_igt():
    a, b = uuid4(), uuid4()
    # Same points everywhere (a shared 1st on the standard seed, a solo 1st each on
    # a boss seed): only the summed IGT of the counted seeds separates them.
    std = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 100),
            _participant(b, ParticipantStatus.FINISHED, 100),
        ]
    )
    boss1 = _race([_participant(a, ParticipantStatus.FINISHED, 300)])
    boss2 = _race([_participant(b, ParticipantStatus.FINISHED, 200)])
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), std),
            (parse_slot("qualifier:boss_rush:1"), boss1),
            (parse_slot("qualifier:boss_rush:2"), boss2),
        ],
    )
    assert [e.total for e in ladder] == [200, 200]
    assert [e.user_id for e in ladder] == [b, a]
    assert ladder[0].rank == 1 and ladder[1].rank == 2


def test_ladder_provisional_false_when_the_faster_counted_seed_is_finished():
    a = uuid4()
    # Single-participant races always score MAX_DAILY_POINTS, so the two seeds tie on
    # points and the count falls to igt_ms: the finished, faster seed is counted, the
    # running, slower seed is not.
    fast_finished = _race([_participant(a, ParticipantStatus.FINISHED, 10)])
    slow_running = _race(
        [_participant(a, ParticipantStatus.FINISHED, 50)], status=RaceStatus.RUNNING
    )
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), fast_finished),
            (parse_slot("qualifier:standard:2"), slow_running),
        ],
    )
    entry = ladder[0]
    assert entry.counted_slots["standard"] == "qualifier:standard:1"
    assert entry.provisional is False


def test_ladder_provisional_true_when_the_faster_counted_seed_is_running():
    a = uuid4()
    fast_running = _race(
        [_participant(a, ParticipantStatus.FINISHED, 10)], status=RaceStatus.RUNNING
    )
    slow_finished = _race([_participant(a, ParticipantStatus.FINISHED, 50)])
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), fast_running),
            (parse_slot("qualifier:standard:2"), slow_finished),
        ],
    )
    entry = ladder[0]
    assert entry.counted_slots["standard"] == "qualifier:standard:1"
    assert entry.provisional is True


def test_ladder_ignores_a_run_in_progress():
    a, b, c = uuid4(), uuid4(), uuid4()
    # b's partial run would otherwise enter the ladder, ranked like a DNF on its
    # depth so far, and dilute the points of the runners behind the leader.
    running = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 40),
            _participant(c, ParticipantStatus.FINISHED, 60),
            _participant(b, ParticipantStatus.PLAYING, 10),
        ],
        status=RaceStatus.RUNNING,
    )
    ladder = compute_ladder(["standard"], [(parse_slot("qualifier:standard:1"), running)])
    assert [e.user_id for e in ladder] == [a, c]
    # c is 2nd of the 2 settled runs (50), not 2nd of 3 (67).
    assert ladder[1].mode_points == {"standard": 50}


def test_ladder_ties_share_rank_and_skip_the_next_rank():
    a, b, c = uuid4(), uuid4(), uuid4()
    # a and b end up with identical (total, igt_total); c is strictly slower on both
    # seeds so its total ties but its igt_total is worse.
    ladder = compute_ladder(
        MODES,
        [
            (
                parse_slot("qualifier:standard:1"),
                _race([_participant(a, ParticipantStatus.FINISHED, 100)]),
            ),
            (
                parse_slot("qualifier:boss_rush:1"),
                _race([_participant(a, ParticipantStatus.FINISHED, 200)]),
            ),
            (
                parse_slot("qualifier:standard:2"),
                _race([_participant(b, ParticipantStatus.FINISHED, 100)]),
            ),
            (
                parse_slot("qualifier:boss_rush:2"),
                _race([_participant(b, ParticipantStatus.FINISHED, 200)]),
            ),
            (
                parse_slot("qualifier:standard:3"),
                _race([_participant(c, ParticipantStatus.FINISHED, 150)]),
            ),
            (
                parse_slot("qualifier:boss_rush:3"),
                _race([_participant(c, ParticipantStatus.FINISHED, 250)]),
            ),
        ],
    )
    by_user = {e.user_id: e for e in ladder}
    assert by_user[a].total == by_user[b].total == 200
    assert by_user[a].rank == 1 and by_user[b].rank == 1
    assert by_user[c].rank == 3


def test_signups_close_the_ladder_in_signup_order():
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
    standard = _race(
        [
            _participant(a, ParticipantStatus.FINISHED, 1_000_000),
            _participant(b, ParticipantStatus.FINISHED, 1_200_000),
        ]
    )
    boss = _race([_participant(a, ParticipantStatus.FINISHED, 900_000)])
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), standard),
            (parse_slot("qualifier:boss_rush:1"), boss),
        ],
        signed_up=[d, a, c],
    )
    # a signed up too, but scored: listed once, through the run, still ranked.
    assert [e.user_id for e in ladder] == [a, b, d, c]
    assert ladder[0].rank == 1
    tail = ladder[2:]
    assert all(e.rank is None and e.total is None and e.modes_scored == 0 for e in tail)
    assert all(e.mode_points == {"standard": None, "boss_rush": None} for e in tail)
    assert all(e.partial == 0 and e.igt_total == 0 and not e.provisional for e in tail)
    assert all(e.counted_slots == {} for e in tail)


def test_signup_rows_take_no_seed():
    a, c = uuid4(), uuid4()
    standard = _race([_participant(a, ParticipantStatus.FINISHED, 1_000_000)])
    boss = _race([_participant(a, ParticipantStatus.FINISHED, 900_000)])
    ladder = compute_ladder(
        MODES,
        [
            (parse_slot("qualifier:standard:1"), standard),
            (parse_slot("qualifier:boss_rush:1"), boss),
        ],
        signed_up=[c],
    )
    groups = compute_qualified(ladder, _config(), {a: False, c: True})
    # Semi A takes seeds 1 and 4: the one ranked runner, then nobody.
    assert groups["semi_a"][0].user_id == a
    assert groups["semi_a"][1].user_id is None
    assert groups["semi_a"][1].note == UNDECIDED
    # A signed-up newcomer without a run does not reach the newcomers' group either.
    assert all(slot.user_id is None for slot in groups["newcomers"])


# --- newcomers --------------------------------------------------------------


def test_newcomer_flags_use_strict_threshold():
    a, b, c = uuid4(), uuid4(), uuid4()
    flags = newcomer_flags({a: 4, b: 5}, threshold=5, user_ids=[a, b, c])
    assert flags == {a: True, b: False, c: True}


# --- qualified groups -------------------------------------------------------


def _ladder_of(*users):
    """Ranked ladder entries in order, one per user."""
    from speedfog_racing.services.event_service import LadderEntry

    return [
        LadderEntry(
            user_id=u,
            mode_points={},
            counted_slots={},
            modes_scored=2,
            total=100 - i,
            partial=100 - i,
            igt_total=0,
            provisional=False,
            rank=i + 1,
        )
        for i, u in enumerate(users)
    ]


def test_qualified_uses_ladder_positions_and_keeps_newcomers_outside_top_seeds():
    u = [uuid4() for _ in range(6)]
    ladder = _ladder_of(*u)
    newcomers = {u[1]: True, u[4]: True, u[5]: True}
    groups = compute_qualified(ladder, _config(), newcomers)
    assert [s.user_id for s in groups["semi_a"]] == [u[0], u[3]]
    assert [s.user_id for s in groups["semi_b"]] == [u[1], u[2]]
    # u[1] is a newcomer but seeded in semi_b: not in the newcomers' group.
    assert [s.user_id for s in groups["newcomers"]] == [u[4], u[5]]


def test_qualified_leaves_slots_open_when_ladder_is_short():
    u = [uuid4() for _ in range(2)]
    groups = compute_qualified(_ladder_of(*u), _config(), {})
    assert [s.user_id for s in groups["semi_a"]] == [u[0], None]
    assert groups["semi_a"][1].note == "TBD"
    assert [s.user_id for s in groups["newcomers"]] == [None, None]


# --- stage results and final field -----------------------------------------


def test_stage_results_sum_points_and_advance_only_when_complete():
    cfg = _config()
    stage = cfg.stage("semi_a")
    a, b, c, d = (uuid4() for _ in range(4))
    order = [a, b, c, d]
    race1 = _race(
        [_participant(u, ParticipantStatus.FINISHED, 100 * (i + 1)) for i, u in enumerate(order)]
    )
    race2 = _race(
        [_participant(u, ParticipantStatus.FINISHED, 100 * (4 - i)) for i, u in enumerate(order)]
    )
    partial = compute_stage_results(stage, [race1, race2], advance=2)
    assert partial.complete is False
    assert all(not e.advances for e in partial.entries)
    # a: 100 + 25, d: 25 + 100, b: 75 + 50, c: 50 + 75 -> four-way points tie in this
    # partial (two-race) state; race3 below breaks it by points alone (225/200/175/150,
    # all distinct), so this test does not exercise the igt tie-break at completion. See
    # test_stage_results_breaks_points_tie_by_igt_total for that.
    race3 = _race(
        [_participant(u, ParticipantStatus.FINISHED, 100 * (i + 1)) for i, u in enumerate(order)]
    )
    full = compute_stage_results(stage, [race1, race2, race3], advance=2)
    assert full.complete is True
    assert [e.user_id for e in full.entries][:2] == [a, b]
    assert [e.advances for e in full.entries] == [True, True, False, False]
    assert full.entries[0].points == 225


def test_stage_results_breaks_points_tie_by_igt_total():
    cfg = _config()
    stage = cfg.stage("newcomers")  # races=2, kind is irrelevant to compute_stage_results
    x, y = uuid4(), uuid4()
    # race1: x wins (100pts, igt 100), y loses (50pts, igt 150).
    race1 = _race(
        [
            _participant(x, ParticipantStatus.FINISHED, 100),
            _participant(y, ParticipantStatus.FINISHED, 150),
        ]
    )
    # race2: y wins (100pts, igt 50), x loses (50pts, igt 300).
    race2 = _race(
        [
            _participant(y, ParticipantStatus.FINISHED, 50),
            _participant(x, ParticipantStatus.FINISHED, 300),
        ]
    )
    # Totals: x = 150pts / 400ms igt, y = 150pts / 200ms igt -> tied on points,
    # y's lower summed igt must sort it first and, with advance=1, only y advances.
    result = compute_stage_results(stage, [race1, race2], advance=1)
    assert result.complete is True
    assert [e.points for e in result.entries] == [150, 150]
    assert [e.user_id for e in result.entries] == [y, x]
    assert [e.advances for e in result.entries] == [True, False]


def test_final_field_labels_undecided_semis():
    cfg = _config()
    final = cfg.final_stage()
    a, b = uuid4(), uuid4()
    done = StageResult(
        complete=True,
        entries=[StageEntry(a, 300, 0, True), StageEntry(b, 200, 0, True)],
    )
    slots = fed_field(final, cfg, {"semi_a": done})
    assert [(s.user_id, s.label) for s in slots[:2]] == [(a, "Semi A"), (b, "Semi A")]
    assert [(s.user_id, s.label) for s in slots[2:]] == [(None, "Top 2 of Semi B")] * 2


def test_final_field_pads_short_decided_stages_to_the_advance_count():
    cfg = _config()
    final = cfg.final_stage()
    a, b = uuid4(), uuid4()
    # Each source stage is complete but produced only one advancing entry (advance=2):
    # the field must still be padded to the full advance count with a placeholder.
    short_a = StageResult(complete=True, entries=[StageEntry(a, 300, 0, True)])
    short_b = StageResult(complete=True, entries=[StageEntry(b, 250, 0, True)])
    slots = fed_field(final, cfg, {"semi_a": short_a, "semi_b": short_b})
    assert [(s.user_id, s.label) for s in slots] == [
        (a, "Semi A"),
        (None, "Top 2 of Semi A"),
        (b, "Semi B"),
        (None, "Top 2 of Semi B"),
    ]


def _quarters_config() -> EventConfig:
    """Four quarters of four into two semis into a final, one race per stage."""
    quarters = [
        ("quarter_a", "Quarter A", [1, 8, 9, 16]),
        ("quarter_b", "Quarter B", [4, 5, 12, 13]),
        ("quarter_c", "Quarter C", [2, 7, 10, 15]),
        ("quarter_d", "Quarter D", [3, 6, 11, 14]),
    ]
    stages: list[dict[str, object]] = [
        {
            "key": key,
            "label": label,
            "kind": "quarter",
            "date": f"2026-10-0{2 + i}T19:00:00Z",
            "races": 1,
            "seeds": seeds,
            "advance": 2,
        }
        for i, (key, label, seeds) in enumerate(quarters)
    ]
    stages += [
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": "2026-10-10T19:00:00Z",
            "races": 1,
            "from": ["quarter_a", "quarter_b"],
            "advance": 2,
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": "2026-10-11T19:00:00Z",
            "races": 1,
            "from": ["quarter_c", "quarter_d"],
            "advance": 2,
        },
        {
            "key": "newcomers",
            "label": "Newcomers",
            "kind": "newcomers",
            "date": "2026-10-18T19:00:00Z",
            "races": 1,
            "size": 2,
        },
        {
            "key": "final",
            "label": "Final",
            "kind": "final",
            "date": "2026-10-25T19:00:00Z",
            "races": 1,
            "from": ["semi_a", "semi_b"],
        },
    ]
    return EventConfig.model_validate(
        {
            "modes": [{"key": m, "label": m} for m in MODES],
            "seeds_per_mode": 2,
            "announced_at": "2026-09-16T18:00:00Z",
            "stages": stages,
        }
    )


def test_quarters_seed_from_the_ladder_and_newcomers_draw_after_seed_16():
    cfg = _quarters_config()
    u = [uuid4() for _ in range(19)]
    newcomers = {u[3]: True, u[16]: True, u[17]: True, u[18]: True}
    groups = compute_qualified(_ladder_of(*u), cfg, newcomers)
    assert list(groups) == ["quarter_a", "quarter_b", "quarter_c", "quarter_d", "newcomers"]
    assert [s.user_id for s in groups["quarter_a"]] == [u[0], u[7], u[8], u[15]]
    # u[3] is a newcomer but seeded 4th (Quarter B): the newcomers' final
    # draws from position 17 on.
    assert [s.user_id for s in groups["newcomers"]] == [u[16], u[17]]


def test_three_rounds_feed_each_other():
    cfg = _quarters_config()
    u = [uuid4() for _ in range(16)]
    quarter_a, semi_a, final = cfg.stage("quarter_a"), cfg.stage("semi_a"), cfg.stage("final")
    assert quarter_a is not None and semi_a is not None and final is not None
    # Quarter A played: seeds 1 and 9 finish first and second.
    order = [u[0], u[8], u[7], u[15]]
    race = _race(
        [
            _participant(user, ParticipantStatus.FINISHED, 100 * (i + 1))
            for i, user in enumerate(order)
        ]
    )
    results = {"quarter_a": compute_stage_results(quarter_a, [race], quarter_a.advance or 0)}
    assert [(s.user_id, s.label) for s in fed_field(semi_a, cfg, results)] == [
        (u[0], "Quarter A"),
        (u[8], "Quarter A"),
        (None, "Top 2 of Quarter B"),
        (None, "Top 2 of Quarter B"),
    ]
    # Nothing of the semis is decided: the final only names where it waits.
    assert [s.label for s in fed_field(final, cfg, results)] == (
        ["Top 2 of Semi A"] * 2 + ["Top 2 of Semi B"] * 2
    )


# --- signature weapon -------------------------------------------------------


def test_signature_weapon_sums_ticks_per_weapon_across_histories():
    fang, uchi = 8030000, 9000000  # catalogue base ids, any affinity or upgrade
    histories = [
        [{"weapons": [{"ids": [fang + 25, uchi + 10], "ticks": 5}]}, {}],
        [{"weapons": [{"ids": [uchi], "ticks": 3}, {"ids": [1], "ticks": 99}]}],
        None,
    ]
    assert signature_weapon(histories) == (uchi, WEAPONS[uchi].name)
    assert signature_weapon([[{"weapons": []}], []]) is None
    # A combo without ticks counts nothing; an exact tie goes to the lower id.
    tied = [[{"weapons": [{"ids": [uchi]}, {"ids": [fang], "ticks": 0}]}]]
    assert signature_weapon(tied) == (fang, WEAPONS[fang].name)


# --- phase ------------------------------------------------------------------

T0 = datetime(2026, 9, 23, 8, tzinfo=UTC)
CUT = datetime(2026, 9, 30, 8, tzinfo=UTC)
FIRST = datetime(2026, 10, 4, 19, tzinfo=UTC)
END = datetime(2026, 10, 26, 0, tzinfo=UTC)


def _undated_quarters() -> EventConfig:
    """This season as configured: quarters and semis left to their races, three per evening."""
    raw = _quarters_config().model_dump(mode="json", by_alias=True)
    for stage in raw["stages"]:
        stage["races"] = 3
        if stage["kind"] in ("quarter", "semi"):
            stage["date"] = None
    return EventConfig.model_validate(raw)


def test_a_stage_date_is_the_config_one_else_its_earliest_race():
    cfg = _undated_quarters()
    monday = datetime(2026, 10, 12, 19, tzinfo=UTC)
    tuesday = monday + timedelta(days=1)
    scheduled = SimpleNamespace(scheduled_at=tuesday, started_at=None)
    # A private race needs no schedule: once started, its start dates the stage.
    private = SimpleNamespace(scheduled_at=None, started_at=monday.replace(tzinfo=None))
    races = {s.key: [] for s in cfg.stages}
    races["quarter_a"] = [
        (parse_slot("quarter_a:2"), scheduled),
        (parse_slot("quarter_a:1"), private),
    ]
    dates = stage_dates(cfg, races)
    assert dates["quarter_a"] == monday  # the naive SQLite value read as UTC
    assert dates["quarter_b"] is None
    assert dates["final"] == datetime(2026, 10, 25, 19, tzinfo=UTC)
    assert race_moment(SimpleNamespace(scheduled_at=None, started_at=None)) is None


def test_the_cut_lasts_until_the_first_scheduled_playoff_race():
    cfg = _undated_quarters()
    race = _slotted("quarter_c:1", RaceStatus.SETUP)
    race.scheduled_at = datetime(2026, 10, 9, 19, tzinfo=UTC)
    event = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END, races=[race])
    assert resolve_stages(event, cfg, datetime(2026, 10, 9, 18, tzinfo=UTC)).phase == "cut"
    assert resolve_stages(event, cfg, datetime(2026, 10, 9, 19, tzinfo=UTC)).phase == "playoffs"
    # With nothing scheduled, the first dated stage (the newcomers') bounds it.
    bare = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END, races=[])
    assert resolve_stages(bare, cfg, datetime(2026, 10, 17, 9, tzinfo=UTC)).phase == "cut"


def test_the_timeline_folds_the_undated_stages_into_one_playoffs_stop():
    event = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END)
    stops = build_timeline(event, _undated_quarters())
    assert [s.kind for s in stops] == ["announce", "open", "cut", "playoffs", "newcomers", "final"]
    assert stops[3].date == CUT
    assert "playoffs" not in [s.kind for s in build_timeline(event, _config())]


def _phase(now, **kw):
    args = dict(
        starts_at=T0,
        qualifier_ends_at=CUT,
        ends_at=END,
        first_stage_at=FIRST,
        last_stage_complete=False,
        override=None,
    )
    args.update(kw)
    return compute_phase(now=now, **args)


@pytest.mark.parametrize(
    "now, expected",
    [
        (T0 - timedelta(days=1), "upcoming"),
        (T0, "qualifier"),
        (CUT - timedelta(seconds=1), "qualifier"),
        (CUT, "cut"),
        (FIRST, "playoffs"),
        (END - timedelta(seconds=1), "playoffs"),
        (END, "finished"),
    ],
)
def test_phase_boundaries(now, expected):
    assert _phase(now) == expected


def test_phase_override_and_completed_last_stage():
    assert _phase(T0, override="playoffs") == "playoffs"
    assert _phase(FIRST + timedelta(days=1), last_stage_complete=True) == "finished"
    assert _phase(T0, first_stage_at=None) == "qualifier"
    assert _phase(CUT, first_stage_at=None) == "playoffs"


def _resolved(cfg: EventConfig, races, now: datetime):
    event = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END, races=races)
    return resolve_stages(event, cfg, now)


def _scheduled(slot: str, at: datetime, status=RaceStatus.SETUP):
    race = _slotted(slot, status)
    race.scheduled_at = at
    return race


def test_a_running_stage_wins_over_one_only_scheduled_later_the_same_day():
    # Quarter A is merely scheduled for later that evening (still in setup);
    # Quarter C is the one actually running. The live rule must win over
    # Quarter A even though Quarter A comes first in bracket order and is
    # also one of today's stages.
    cfg = _undated_quarters()
    evening = datetime(2026, 10, 9, 19, tzinfo=UTC)
    races = [
        _scheduled("quarter_a:1", evening + timedelta(hours=3)),
        _scheduled("quarter_c:1", evening, RaceStatus.RUNNING),
    ]
    now = evening + timedelta(minutes=20)
    assert current_stage_key(cfg, _resolved(cfg, races, now), now) == "quarter_c"


def test_current_stage_prefers_a_started_match_over_one_only_scheduled_the_same_day():
    # Quarter C is between its two races (race 1 finished, race 2 not yet
    # started); Quarter A is scheduled later the same evening but has not
    # started. Nothing is RUNNING, so the live rule is silent, and list order
    # alone (Quarter A comes before Quarter C in bracket order) must not win:
    # the started, in-progress match does.
    cfg = _undated_quarters()
    quarter_c_race1_at = datetime(2026, 10, 9, 19, tzinfo=UTC)
    quarter_a_race1_at = datetime(2026, 10, 9, 22, tzinfo=UTC)
    races = [
        _scheduled("quarter_c:1", quarter_c_race1_at, RaceStatus.FINISHED),
        _scheduled("quarter_c:2", quarter_c_race1_at + timedelta(hours=1, minutes=30)),
        _scheduled("quarter_a:1", quarter_a_race1_at),
    ]
    now = quarter_c_race1_at + timedelta(minutes=45)
    assert current_stage_key(cfg, _resolved(cfg, races, now), now) == "quarter_c"


def test_a_match_spread_over_two_evenings_stays_current_on_the_second():
    cfg = _undated_quarters()
    monday = datetime(2026, 10, 12, 19, tzinfo=UTC)
    races = [
        _scheduled("quarter_b:1", monday, RaceStatus.FINISHED),
        _scheduled("quarter_b:2", monday + timedelta(days=1)),
    ]
    tuesday_noon = datetime(2026, 10, 13, 12, tzinfo=UTC)
    resolved = _resolved(cfg, races, tuesday_noon)
    assert current_stage_key(cfg, resolved, tuesday_noon) == "quarter_b"


def test_nothing_is_current_on_a_day_without_a_match():
    cfg = _undated_quarters()
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    assert current_stage_key(cfg, _resolved(cfg, [], now), now) is None


def test_the_next_stage_never_skips_an_unscheduled_round():
    cfg = _undated_quarters()
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    # Nothing scheduled: the newcomers' final (drawn from the ladder) is the
    # next evening; the final waits on semis nobody has a date for.
    assert next_stage_key(cfg, _resolved(cfg, [], now), now) == "newcomers"
    later = datetime(2026, 10, 19, 12, tzinfo=UTC)
    assert next_stage_key(cfg, _resolved(cfg, [], later), later) is None
    races = [_scheduled("quarter_d:1", datetime(2026, 10, 11, 19, tzinfo=UTC))]
    assert next_stage_key(cfg, _resolved(cfg, races, now), now) == "quarter_d"


def test_the_next_stage_reads_dated_stages_in_date_order():
    cfg = _config()
    now = datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert next_stage_key(cfg, _resolved(cfg, [], now), now) == "semi_b"


def test_timeline_uses_announced_at_when_present():
    cfg = _config()
    event = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END)
    stops = build_timeline(event, cfg)
    assert [s.kind for s in stops] == [
        "announce",
        "open",
        "cut",
        "semi",
        "semi",
        "newcomers",
        "final",
    ]
    assert stops[0].date == datetime(2026, 9, 16, 18, tzinfo=UTC)
    cfg.announced_at = None
    assert build_timeline(event, cfg)[0].date == T0 - timedelta(days=7)


def test_build_timeline_normalizes_naive_dates_without_mutating_event():
    """A SQLite round-trip drops the UTC offset; the fix must not write it back."""
    cfg = _config()
    naive_event = SimpleNamespace(
        starts_at=T0.replace(tzinfo=None),
        qualifier_ends_at=CUT.replace(tzinfo=None),
        ends_at=END.replace(tzinfo=None),
    )
    stops = build_timeline(naive_event, cfg)
    assert all(s.date.tzinfo is not None for s in stops)
    assert naive_event.starts_at.tzinfo is None
    assert naive_event.qualifier_ends_at.tzinfo is None
    assert naive_event.ends_at.tzinfo is None


# --- resolve_stages -----------------------------------------------------------


def _slotted(slot: str, status=RaceStatus.FINISHED, participants=()):
    return SimpleNamespace(
        event_slot=slot,
        status=status,
        participants=list(participants),
        scheduled_at=None,
        started_at=None,
    )


def test_resolve_stages_sorts_the_slots_and_drops_what_the_config_does_not_know():
    cfg = _config()
    races = [
        _slotted("semi_a:2", RaceStatus.RUNNING),
        _slotted("nonsense"),
        _slotted("qualifier:boss_rush:1"),
        _slotted("semi_a:1"),
        _slotted("qualifier:standard:2"),
        _slotted("qualifier:standard:1"),
        _slotted("qualifier:sprint:1"),
        _slotted("quarter_z:1"),
    ]
    event = SimpleNamespace(starts_at=T0, qualifier_ends_at=CUT, ends_at=END, races=races)
    resolved = resolve_stages(event, cfg, FIRST)
    assert [str(s) for s, _ in resolved.qualifier] == [
        "qualifier:standard:1",
        "qualifier:standard:2",
        "qualifier:boss_rush:1",
    ]
    assert [str(s) for s, _ in resolved.stage_races["semi_a"]] == ["semi_a:1", "semi_a:2"]
    assert set(resolved.stage_races) == {"semi_a", "semi_b", "newcomers", "final"}
    assert resolved.results["semi_a"].complete is False
    assert resolved.phase == "playoffs"
