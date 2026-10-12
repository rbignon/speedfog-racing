"""Validation rules of the event config document."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from speedfog_racing.schemas import EventConfig, EventUpsertRequest

from .event_fixtures import bracketed, stages_of


def _valid(doc):
    return EventConfig.model_validate(bracketed(doc))


def _config(**overrides):
    base = {
        "modes": [
            {"key": "standard", "label": "Standard"},
            {"key": "boss_rush", "label": "Boss Rush"},
        ],
        "seeds_per_mode": 2,
        "stages": [
            {
                "key": "semi_a",
                "label": "Semi A",
                "kind": "semi",
                "date": "2026-10-04T19:00:00Z",
                "races": 3,
                "seeds": [1, 4],
                "advance": 2,
            },
            {
                "key": "semi_b",
                "label": "Semi B",
                "kind": "semi",
                "date": "2026-10-11T19:00:00Z",
                "races": 3,
                "seeds": [2, 3],
                "advance": 2,
            },
            {
                "key": "newcomers",
                "label": "Newcomers",
                "kind": "newcomers",
                "date": "2026-10-18T19:00:00Z",
                "races": 2,
                "size": 4,
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
        "rules": ["One sitting per run."],
        "announced_at": "2026-09-16T18:00:00Z",
    }
    base.update(overrides)
    return base


def test_valid_config_exposes_lookups():
    cfg = _valid(_config())
    assert cfg.mode_keys() == ["standard", "boss_rush"]
    assert cfg.stage("final") is not None and cfg.stage("final").from_ == ["semi_a", "semi_b"]
    assert cfg.final_stage() is not None and cfg.final_stage().key == "final"
    assert cfg.phase_override is None


def test_duplicate_mode_keys_rejected():
    modes = [{"key": "standard", "label": "A"}, {"key": "standard", "label": "B"}]
    with pytest.raises(ValidationError, match="unique"):
        _valid(_config(modes=modes))


def test_semi_requires_distinct_seeds():
    stages = _config()["stages"]
    stages[0]["seeds"] = [1, 1]
    with pytest.raises(ValidationError, match="seeds"):
        _valid(_config(stages=stages))


def test_seeds_must_be_distinct_across_stages():
    stages = _config()["stages"]
    stages[1]["seeds"] = [1, 3]  # seed 1 already used by semi_a
    with pytest.raises(ValidationError, match="distinct across"):
        _valid(_config(stages=stages))


def test_semi_seeds_must_cover_the_ladder_from_one():
    """A gap leaves those ladder positions to no semi."""
    stages = _config()["stages"]
    stages[1]["seeds"] = [2, 5]  # 1, 2, 4, 5 across the semis: 3 goes nowhere
    with pytest.raises(ValidationError, match="without a gap"):
        _valid(_config(stages=stages))
    stages[0]["seeds"] = [2, 4]
    stages[1]["seeds"] = [3, 5]  # nobody holds seed 1
    with pytest.raises(ValidationError, match="without a gap"):
        _valid(_config(stages=stages))


def test_stage_dates_must_ascend():
    stages = _config()["stages"]
    stages[1]["date"] = "2026-10-03T19:00:00Z"
    with pytest.raises(ValidationError, match="ascending"):
        _valid(_config(stages=stages))


def test_phase_override_must_be_a_phase():
    with pytest.raises(ValidationError, match="phase_override"):
        _valid(_config(phase_override="halftime"))


def test_playoff_rules_share_the_rule_length_cap():
    with pytest.raises(ValidationError, match="300"):
        _valid(_config(playoff_rules=["x" * 301]))


def test_facts_reject_blank_or_overlong_text():
    with pytest.raises(ValidationError, match="blank"):
        _valid(_config(facts=[{"title": " ", "lines": ["4 Sundays"]}]))
    with pytest.raises(ValidationError, match="fact line"):
        _valid(_config(facts=[{"title": "Playoffs", "lines": ["4 Sundays", " "]}]))
    with pytest.raises(ValidationError, match="fact line"):
        _valid(_config(facts=[{"title": "Modes", "lines": ["x" * 61]}]))
    with pytest.raises(ValidationError, match="lines"):
        _valid(_config(facts=[{"title": "Modes", "lines": []}]))


def test_announced_at_must_be_timezone_aware():
    with pytest.raises(ValidationError, match="announced_at"):
        _valid(_config(announced_at="2026-10-01T10:00:00"))


def test_stage_date_must_be_timezone_aware():
    stages = _config()["stages"]
    stages[0]["date"] = "2026-10-04T19:00:00"
    with pytest.raises(ValidationError, match="timezone-aware datetime"):
        _valid(_config(stages=stages))


def test_a_stage_date_may_be_a_day_whose_time_is_not_set():
    stages = _config()["stages"]
    stages[3]["date"] = "2026-10-25"
    cfg = _valid(_config(stages=stages))
    # Stored as typed, so the admin editor hands the day back unchanged.
    dumped = stages_of(cfg.model_dump(mode="json", by_alias=True))
    assert next(s for s in dumped if s["key"] == "final")["date"] == "2026-10-25"


def test_a_day_takes_part_in_the_ascending_order():
    stages = _config()["stages"]
    stages[1]["date"] = "2026-10-04"  # the day of semi_a, which is at 19:00Z
    with pytest.raises(ValidationError, match="ascending"):
        _valid(_config(stages=stages))
    stages[1]["date"] = "2026-10-05"
    _valid(_config(stages=stages))


def test_event_upsert_rejects_naive_dates():
    """A naive starts_at/ends_at must be rejected up front: compared against an aware
    stage date it would raise TypeError (a 500), and stored as-is it would silently
    shift on the TIMESTAMPTZ column."""
    base_doc = {
        "slug": "season-one",
        "name": "Season One",
        "starts_at": "2026-09-23T08:00:00+00:00",
        "qualifier_ends_at": "2026-09-30T08:00:00+00:00",
        "ends_at": "2026-10-26T00:00:00+00:00",
        "config": bracketed(_config()),
    }
    naive_starts = dict(base_doc, starts_at="2026-09-23T08:00:00")
    with pytest.raises(ValidationError, match="starts_at"):
        EventUpsertRequest.model_validate(naive_starts)

    naive_ends = dict(base_doc, ends_at="2026-10-26T00:00:00")
    with pytest.raises(ValidationError, match="ends_at"):
        EventUpsertRequest.model_validate(naive_ends)


def test_event_upsert_rejects_announcement_at_or_after_the_opening():
    """The announcement is the newcomer cut: at or after the opening, the
    qualifier's own runs would count towards it."""
    doc = {
        "slug": "season-one",
        "name": "Season One",
        "starts_at": "2026-09-23T08:00:00+00:00",
        "qualifier_ends_at": "2026-09-30T08:00:00+00:00",
        "ends_at": "2026-10-26T00:00:00+00:00",
        "config": bracketed(_config(announced_at="2026-09-23T08:00:00+00:00")),
    }
    with pytest.raises(ValidationError, match="announced_at must be before starts_at"):
        EventUpsertRequest.model_validate(doc)


def test_from_alias_round_trips_through_json_dump():
    cfg = _valid(_config())
    dumped = cfg.model_dump(mode="json", by_alias=True)
    final_stage_dump = next(s for s in stages_of(dumped) if s["key"] == "final")
    assert final_stage_dump["from"] == ["semi_a", "semi_b"]
    assert "from_" not in final_stage_dump

    restored = EventConfig.model_validate(dumped)
    assert restored.stage("final") is not None
    assert restored.stage("final").from_ == cfg.stage("final").from_


def _quarters(**overrides):
    """This season's shape: four quarters into two semis into a final."""

    def quarter(key: str, label: str, seeds: list[int], day: int) -> dict:
        return {
            "key": key,
            "label": label,
            "kind": "quarter",
            "date": f"2026-10-0{day}T19:00:00Z",
            "races": 3,
            "seeds": seeds,
            "advance": 2,
        }

    stages = [
        quarter("quarter_a", "Quarter A", [1, 8, 9, 16], 2),
        quarter("quarter_b", "Quarter B", [4, 5, 12, 13], 3),
        quarter("quarter_c", "Quarter C", [2, 7, 10, 15], 4),
        quarter("quarter_d", "Quarter D", [3, 6, 11, 14], 5),
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": "2026-10-10T19:00:00Z",
            "races": 3,
            "from": ["quarter_a", "quarter_b"],
            "advance": 2,
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "date": "2026-10-11T19:00:00Z",
            "races": 3,
            "from": ["quarter_c", "quarter_d"],
            "advance": 2,
        },
        {
            "key": "newcomers",
            "label": "Newcomers",
            "kind": "newcomers",
            "date": "2026-10-18T19:00:00Z",
            "races": 3,
            "size": 4,
        },
        {
            "key": "final",
            "label": "Final",
            "kind": "final",
            "date": "2026-10-25T19:00:00Z",
            "races": 3,
            "from": ["semi_a", "semi_b"],
        },
    ]
    return _config(stages=stages, **overrides)


def test_quarters_feed_semis_that_feed_the_final():
    cfg = _valid(_quarters())
    semi_a, final = cfg.stage("semi_a"), cfg.stage("final")
    assert semi_a is not None and final is not None
    # A fed stage seats what its sources send on: two quarters of 2 each.
    assert cfg.field_size(semi_a) == 4
    assert cfg.field_size(final) == 4


def test_advance_sits_on_the_stage_that_sends_runners_on():
    stages = _quarters()["stages"]
    stages[-1]["advance"] = 2  # the final takes from the semis, nothing takes from it
    with pytest.raises(ValidationError, match="no stage takes from it"):
        _valid(_config(stages=stages))
    stages = _quarters()["stages"]
    del stages[0]["advance"]  # quarter_a feeds semi_a without saying how many
    with pytest.raises(ValidationError, match="needs advance"):
        _valid(_config(stages=stages))


def test_from_only_names_earlier_stages():
    stages = _quarters()["stages"]
    stages[4]["from"] = ["quarter_a", "semi_b"]  # semi_b comes after semi_a
    with pytest.raises(ValidationError, match="placed before"):
        _valid(_config(stages=stages))
    stages = _quarters()["stages"]
    stages[4]["from"] = ["quarter_a", "nowhere"]
    with pytest.raises(ValidationError, match="placed before"):
        _valid(_config(stages=stages))


def test_a_whole_stage_cannot_feed_two_stages():
    stages = _quarters()["stages"]
    stages[5]["from"] = ["quarter_c", "quarter_a"]  # quarter_a already feeds semi_a
    with pytest.raises(ValidationError, match="taken more than once"):
        _valid(_config(stages=stages))


def test_a_stage_takes_its_field_from_exactly_one_source():
    stages = _config()["stages"]
    stages[3]["seeds"] = [5]  # the final would take seeds and semi runners at once
    with pytest.raises(ValidationError, match="exactly one of seeds or from"):
        _valid(_config(stages=stages))
    stages = _config()["stages"]
    del stages[3]["from"]  # nor may it take nothing at all
    with pytest.raises(ValidationError, match="exactly one of seeds or from"):
        _valid(_config(stages=stages))


def test_advance_never_exceeds_the_field_it_comes_from():
    stages = _config()["stages"]
    stages[0]["advance"] = 3  # semi_a seats 2 runners
    with pytest.raises(ValidationError, match="exceeds its field of 2"):
        _valid(_config(stages=stages))


def test_one_final_at_most():
    stages = _quarters()["stages"]
    stages[5]["kind"] = "final"
    with pytest.raises(ValidationError, match="at most one final"):
        _valid(_config(stages=stages))


def test_a_stage_may_leave_its_date_to_its_races():
    stages = _quarters()["stages"]
    for stage in stages[:6]:
        del stage["date"]  # quarters and semis are scheduled with their players
    cfg = _valid(_config(stages=stages))
    assert [s.key for s in cfg.stages if s.date is not None] == ["final", "newcomers"]


def test_only_the_dated_stages_must_ascend():
    stages = _quarters()["stages"]
    del stages[0]["date"]
    stages[1]["date"] = "2026-10-20T19:00:00Z"  # after semi_a's date
    with pytest.raises(ValidationError, match="ascending"):
        _valid(_config(stages=stages))


def test_upsert_reads_the_window_against_the_dated_stages():
    stages = _quarters()["stages"]
    for stage in stages[:6]:
        del stage["date"]
    doc = {
        "slug": "season-one",
        "name": "Season One",
        "starts_at": "2026-09-23T08:00:00+00:00",
        "qualifier_ends_at": "2026-10-08T08:00:00+00:00",
        "ends_at": "2026-10-26T00:00:00+00:00",
        "config": bracketed(_config(stages=stages)),
    }
    EventUpsertRequest.model_validate(doc)
    late_cut = dict(doc, qualifier_ends_at="2026-10-19T08:00:00+00:00")  # after the newcomers
    with pytest.raises(ValidationError, match="first dated stage"):
        EventUpsertRequest.model_validate(late_cut)
    # A day without a time counts from noon UTC.
    stages[6]["date"] = "2026-10-08"
    stages[7]["date"] = "2026-10-25"
    EventUpsertRequest.model_validate(dict(doc, config=bracketed(_config(stages=stages))))
    late_end = dict(
        doc, config=bracketed(_config(stages=stages)), ends_at="2026-10-25T12:00:00+00:00"
    )
    with pytest.raises(ValidationError, match="last dated stage"):
        EventUpsertRequest.model_validate(late_end)


SHOWCASE = {"key": "showcase", "label": "Ignite Showcase", "races": 3}


def test_showcase_keys_share_the_slot_namespace_with_stages():
    # A race attaches to "<key>:<n>" whether the key names a stage or a showcase.
    with pytest.raises(ValidationError, match="unique"):
        _valid(_config(showcases=[dict(SHOWCASE, key="final")]))
    with pytest.raises(ValidationError, match="unique"):
        _valid(_config(showcases=[SHOWCASE, SHOWCASE]))


def test_a_showcase_date_stays_out_of_the_bracket_order():
    # Before the first stage and after the final, listed backwards: only stages ascend.
    early = dict(SHOWCASE, key="warmup", date="2026-09-20T19:00:00Z")
    late = dict(SHOWCASE, date="2026-11-01T19:00:00Z")
    _valid(_config(showcases=[late, early]))
    naive = dict(SHOWCASE, date="2026-11-01T19:00:00")
    with pytest.raises(ValidationError, match="timezone-aware datetime"):
        _valid(_config(showcases=[naive]))
    _valid(_config(showcases=[dict(SHOWCASE, date="2026-11-01")]))


def _round_of_32_stages() -> list[dict[str, object]]:
    """Eight snake-seeded groups of four into quarters, semis and the final."""
    groups = [
        ("a", [1, 16, 17, 32]),
        ("b", [8, 9, 24, 25]),
        ("c", [4, 13, 20, 29]),
        ("d", [5, 12, 21, 28]),
        ("e", [2, 15, 18, 31]),
        ("f", [7, 10, 23, 26]),
        ("g", [3, 14, 19, 30]),
        ("h", [6, 11, 22, 27]),
    ]
    stages: list[dict[str, object]] = [
        {
            "key": f"group_{x}",
            "label": f"Group {x.upper()}",
            "kind": "round",
            "races": 3,
            "seeds": seeds,
            "advance": 2,
        }
        for x, seeds in groups
    ]
    stages += [
        {
            "key": f"quarter_{q}",
            "label": f"Quarter {q.upper()}",
            "kind": "quarter",
            "races": 3,
            "from": [f"group_{a}", f"group_{b}"],
            "advance": 2,
        }
        for q, (a, b) in zip("abcd", [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")])
    ]
    stages += [
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "races": 3,
            "from": ["quarter_a", "quarter_b"],
            "advance": 2,
        },
        {
            "key": "semi_b",
            "label": "Semi B",
            "kind": "semi",
            "races": 3,
            "from": ["quarter_c", "quarter_d"],
            "advance": 2,
        },
        {
            "key": "final",
            "label": "Final",
            "kind": "final",
            "date": "2026-11-01T19:00:00Z",
            "races": 3,
            "from": ["semi_a", "semi_b"],
        },
    ]
    return stages


def test_a_round_of_32_feeds_quarters_semis_and_the_final():
    cfg = _valid(_config(stages=_round_of_32_stages()))
    quarter_a, final = cfg.stage("quarter_a"), cfg.stage("final")
    assert quarter_a is not None and final is not None
    # Two groups send two runners each; two semis send two each.
    assert cfg.field_size(quarter_a) == 4
    assert cfg.field_size(final) == 4


def test_withdrawn_names_must_be_unique_whatever_their_case():
    with pytest.raises(ValidationError, match="withdrawn"):
        _valid(_config(withdrawn=["Ana", " ana"]))


def test_withdrawn_names_must_not_be_blank():
    with pytest.raises(ValidationError, match="withdrawn"):
        _valid(_config(withdrawn=["  "]))


def test_caster_languages_names_are_unique_whatever_their_case():
    with pytest.raises(ValidationError, match="caster_languages"):
        _valid(_config(caster_languages={"Karssi": "FR", " karssi": "FR"}))


def test_caster_languages_names_must_not_be_blank():
    with pytest.raises(ValidationError, match="caster_languages"):
        _valid(_config(caster_languages={"  ": "EN"}))


@pytest.mark.parametrize("code", ["fr", "F", "FREN", "F1", ""])
def test_caster_languages_codes_are_two_or_three_capitals(code):
    with pytest.raises(ValidationError, match="caster_languages"):
        _valid(_config(caster_languages={"karssi": code}))


def test_caster_languages_take_short_capital_codes():
    cfg = _valid(_config(caster_languages={"karssi": "FR", "itzcbd": "EN", "vela": "ESP"}))
    assert cfg.caster_languages["vela"] == "ESP"


def _two_brackets(**overrides):
    def stage(key, label, kind, **fields):
        return {"key": key, "label": label, "kind": kind, "races": 3, **fields}

    base = {
        "modes": [{"key": "standard", "label": "Standard"}],
        "announced_at": "2026-09-16T18:00:00Z",
        "brackets": [
            {
                "key": "main",
                "label": "Top 8",
                "entry": "all",
                "stages": [
                    stage("semi_a", "Semi A", "semi", seeds=[1, 4, 5, 8], advance=2),
                    stage("semi_b", "Semi B", "semi", seeds=[2, 3, 6, 7], advance=2),
                    stage(
                        "final",
                        "Final",
                        "final",
                        date="2026-11-01T19:00:00Z",
                        **{"from": ["semi_a", "semi_b"]},
                    ),
                ],
            },
            {
                "key": "newcomers",
                "label": "Newcomers",
                "entry": "newcomers",
                "stages": [
                    stage(
                        "newcomers_semi_a",
                        "Newcomers semi A",
                        "semi",
                        seeds=[1, 4, 5, 8],
                        advance=2,
                    ),
                    stage(
                        "newcomers_semi_b",
                        "Newcomers semi B",
                        "semi",
                        seeds=[2, 3, 6, 7],
                        advance=2,
                    ),
                    stage(
                        "newcomers_final",
                        "Newcomers' final",
                        "final",
                        date="2026-10-25T19:00:00Z",
                        **{"from": ["newcomers_semi_a", "newcomers_semi_b"]},
                    ),
                ],
            },
        ],
    }
    base.update(overrides)
    return base


def _newcomers_stages(doc):
    return doc["brackets"][1]["stages"]


def test_brackets_reuse_seed_numbers_flatten_in_order_and_date_apart():
    # Seeds 1 to 8 in both brackets, and the newcomers' final (25 Oct) listed
    # after the final (1 Nov): each bracket checks its own seeds and dates.
    cfg = EventConfig.model_validate(_two_brackets())
    assert [s.key for s in cfg.stages] == [
        "semi_a",
        "semi_b",
        "final",
        "newcomers_semi_a",
        "newcomers_semi_b",
        "newcomers_final",
    ]
    assert cfg.final_stage() is not None and cfg.final_stage().key == "final"
    assert cfg.brackets[1].closing_stage().key == "newcomers_final"
    assert cfg.field_size(cfg.stage("newcomers_final")) == 4


def test_the_champions_final_is_the_first_brackets_even_without_one():
    doc = _two_brackets()
    main = doc["brackets"][0]
    main["stages"] = [{**main["stages"][0], "seeds": [1, 2, 3, 4], "advance": None}]
    cfg = EventConfig.model_validate(doc)
    assert cfg.final_stage() is None
    assert cfg.brackets[0].closing_stage().key == "semi_a"


def test_from_never_reaches_into_another_bracket():
    doc = _two_brackets()
    _newcomers_stages(doc)[2]["from"] = ["newcomers_semi_a", "semi_b"]
    with pytest.raises(ValidationError, match="its own bracket"):
        EventConfig.model_validate(doc)


def test_a_bracket_crowns_one_final_at_most():
    doc = _two_brackets()
    _newcomers_stages(doc)[0]["kind"] = "final"
    with pytest.raises(ValidationError, match="at most one final"):
        EventConfig.model_validate(doc)


def test_seeds_cover_each_brackets_pool_from_one():
    doc = _two_brackets()
    _newcomers_stages(doc)[0]["seeds"] = [1, 4, 5, 9]
    with pytest.raises(ValidationError, match="without a gap"):
        EventConfig.model_validate(doc)


def test_stage_labels_are_unique_across_brackets():
    doc = _two_brackets()
    _newcomers_stages(doc)[0]["label"] = "Semi A"
    with pytest.raises(ValidationError, match="labels must be unique"):
        EventConfig.model_validate(doc)


def test_bracket_keys_are_unique():
    doc = _two_brackets()
    doc["brackets"][1]["key"] = "main"
    with pytest.raises(ValidationError, match="bracket keys must be unique"):
        EventConfig.model_validate(doc)


def test_a_newcomers_bracket_needs_announced_at():
    with pytest.raises(ValidationError, match="a newcomers bracket needs announced_at"):
        EventConfig.model_validate(_two_brackets(announced_at=None))
    doc = _two_brackets(announced_at=None)
    doc["brackets"] = doc["brackets"][:1]
    EventConfig.model_validate(doc)


def test_dates_ascend_within_a_bracket():
    doc = _two_brackets()
    _newcomers_stages(doc)[0]["date"] = "2026-10-26T19:00:00Z"
    with pytest.raises(ValidationError, match="ascending"):
        EventConfig.model_validate(doc)


def test_a_bracket_holds_a_stage_at_least():
    doc = _two_brackets()
    doc["brackets"][1]["stages"] = []
    with pytest.raises(ValidationError):
        EventConfig.model_validate(doc)


def test_a_flat_stage_list_is_refused():
    # A document the migration missed must not read as an event without playoffs.
    doc = _two_brackets()
    doc["stages"] = doc.pop("brackets")[0]["stages"]
    with pytest.raises(ValidationError, match="stages moved into brackets"):
        EventConfig.model_validate(doc)


def test_upsert_reads_the_window_against_the_earliest_and_latest_stage():
    doc = {
        "slug": "season-one",
        "name": "Season One",
        "starts_at": "2026-09-23T08:00:00+00:00",
        "qualifier_ends_at": "2026-10-08T08:00:00+00:00",
        "ends_at": "2026-11-02T00:00:00+00:00",
        "config": _two_brackets(),
    }
    EventUpsertRequest.model_validate(doc)
    # The newcomers' final (25 Oct) is listed last yet comes first.
    with pytest.raises(ValidationError, match="first dated stage"):
        EventUpsertRequest.model_validate(dict(doc, qualifier_ends_at="2026-10-26T08:00:00+00:00"))
    with pytest.raises(ValidationError, match="last dated stage"):
        EventUpsertRequest.model_validate(dict(doc, ends_at="2026-10-31T00:00:00+00:00"))


def _crossed(**semis):
    """``_quarters`` with each semi taking one place of every quarter."""
    doc = bracketed(_quarters())
    stages = {s["key"]: s for s in stages_of(doc)}
    stages["semi_a"]["from"] = semis.get(
        "semi_a", ["quarter_a:1", "quarter_b:2", "quarter_c:1", "quarter_d:2"]
    )
    stages["semi_b"]["from"] = semis.get(
        "semi_b", ["quarter_a:2", "quarter_b:1", "quarter_c:2", "quarter_d:1"]
    )
    return doc


def test_semis_can_take_one_place_of_every_quarter():
    cfg = EventConfig.model_validate(_crossed())
    semi_a = cfg.stage("semi_a")
    assert semi_a is not None
    assert semi_a.sources == [
        ("quarter_a", 1),
        ("quarter_b", 2),
        ("quarter_c", 1),
        ("quarter_d", 2),
    ]
    assert semi_a.source_keys == ["quarter_a", "quarter_b", "quarter_c", "quarter_d"]
    assert cfg.field_size(semi_a) == 4


def test_a_place_must_exist_and_be_taken_exactly_once():
    with pytest.raises(ValidationError, match="places 3 do not exist"):
        EventConfig.model_validate(
            _crossed(semi_a=["quarter_a:1", "quarter_b:2", "quarter_c:1", "quarter_d:3"])
        )
    with pytest.raises(ValidationError, match="taken more than once"):
        EventConfig.model_validate(
            _crossed(semi_a=["quarter_a:2", "quarter_b:2", "quarter_c:1", "quarter_d:2"])
        )
    with pytest.raises(ValidationError, match="nobody takes"):
        EventConfig.model_validate(_crossed(semi_a=["quarter_b:2", "quarter_c:1", "quarter_d:2"]))


def test_a_whole_stage_and_one_of_its_places_overlap():
    with pytest.raises(ValidationError, match="taken more than once"):
        EventConfig.model_validate(
            _crossed(semi_a=["quarter_a", "quarter_b:2", "quarter_c:1", "quarter_d:2"])
        )


def test_a_from_item_is_a_key_or_a_key_and_a_place():
    for bad in ("quarter_a:0", "quarter_a:x", "quarter_a:²", ":1"):
        with pytest.raises(ValidationError, match="key or key:place"):
            EventConfig.model_validate(
                _crossed(semi_a=[bad, "quarter_b:2", "quarter_c:1", "quarter_d:2"])
            )
