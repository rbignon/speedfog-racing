import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventLiveMatches from "$lib/components/events/EventLiveMatches.svelte";
import type { Caster, EventStage, Race, User } from "$lib/api";
import type { LiveMatch } from "$lib/events";

const NOW = new Date("2026-10-18T17:25:00Z");

const person = (id: string): User => ({
  id,
  twitch_username: id,
  twitch_display_name: null,
  twitch_avatar_url: null,
});

function race(id: string, overrides: Partial<Race> = {}): Race {
  return {
    id,
    status: "running",
    casters: [],
    participant_previews: [],
    scheduled_at: null,
    started_at: "2026-10-18T17:02:00Z",
    finished_at: null,
    seed_total_layers: 9,
    ...overrides,
  } as Race;
}

function stage(key: string, overrides: Partial<EventStage> = {}): EventStage {
  return {
    key,
    label: key,
    kind: "round",
    bracket: "main",
    date: null,
    date_fixed: false,
    time_set: true,
    from: [],
    advance: null,
    races_expected: 3,
    complete: false,
    walkover: false,
    modes: ["Standard", "Boss Rush", "UWYG"],
    races: [],
    results: [],
    field: [],
    ...overrides,
  };
}

function live(s: EventStage, raceId = `${s.key}-r1`): LiveMatch {
  const entry = {
    slot: `${s.key}:1`,
    index: 1,
    race: race(raceId),
    points: {},
    live: [],
  };
  return { stage: { ...s, races: [entry] }, state: "live", race: entry };
}

describe("EventLiveMatches", () => {
  it("gives a lone match the wide panel and two matches a panel each", () => {
    const cast = live(stage("group_h"));
    cast.race!.race.casters = [
      { id: "c1", user: person("karssi"), is_live: false, stream_url: null },
    ];
    const one = render(EventLiveMatches, {
      matches: [cast],
      stages: [],
      languages: {},
      now: NOW,
    });
    expect(one.container.querySelectorAll(".match.wide").length).toBe(1);
    const two = render(EventLiveMatches, {
      matches: [live(stage("group_h")), live(stage("group_d"))],
      stages: [],
      languages: {},
      now: NOW,
    });
    expect(two.container.querySelectorAll(".match").length).toBe(2);
    expect(two.container.querySelector(".match.wide")).toBeNull();
  });

  it("leaves the full width to a lone match's table when nobody casts it", () => {
    const { container } = render(EventLiveMatches, {
      matches: [live(stage("group_h"))],
      stages: [],
      languages: {},
      now: NOW,
    });
    expect(container.querySelector(".match")).not.toBeNull();
    expect(container.querySelector(".match.wide")).toBeNull();
  });

  it("draws the cut line under the last runner going on and links the running race", () => {
    const runners = ["a", "b", "c", "d"].map(person);
    const s = stage("group_h", {
      advance: 2,
      results: runners.map((user, i) => ({
        user,
        newcomer: false,
        points: 100 - i * 30,
        igt_total: 0,
        advances: false,
        signature_weapon: null,
      })),
    });
    const { container } = render(EventLiveMatches, {
      matches: [live(s, "r-live")],
      stages: [s],
      languages: {},
      now: NOW,
    });
    const rows = [...container.querySelectorAll("tbody tr")];
    expect(rows.map((r) => r.classList.contains("cut"))).toEqual([
      false,
      false,
      true,
      false,
      false,
    ]);
    expect(
      container.querySelector('.head a[href="/race/r-live"]')?.textContent,
    ).toBe("Race page");
  });

  it("dates a next race set on another evening, so it never reads as tonight", () => {
    const s = stage("group_g", {
      races: [
        {
          slot: "group_g:1",
          index: 1,
          race: race("r1", {
            status: "finished",
            finished_at: "2026-10-12T21:00:00Z",
          }),
          points: {},
          live: [],
        },
        {
          slot: "group_g:2",
          index: 2,
          race: race("r2", {
            status: "setup",
            scheduled_at: "2026-10-14T20:00:00Z",
          }),
          points: {},
          live: [],
        },
      ],
    });
    const { container } = render(EventLiveMatches, {
      matches: [{ stage: s, state: "between", race: s.races[1] }],
      stages: [s],
      languages: {},
      now: new Date("2026-10-12T21:30:00Z"),
    });
    expect(container.querySelector(".meta")?.textContent).toContain("14 Oct");
  });

  it("tags a caster with their language and sends a caster off air to their channel", () => {
    const caster: Caster = {
      id: "c1",
      user: person("karssi"),
      is_live: false,
      stream_url: null,
    };
    const s = stage("group_h");
    const match = live(s);
    // The stage's race entry and match.race are the same object.
    match.race!.race.casters = [caster];
    const { container, getByText } = render(EventLiveMatches, {
      matches: [match],
      stages: [s],
      languages: { karssi: "FR" },
      now: NOW,
    });
    expect(getByText("FR")).toBeTruthy();
    expect(container.querySelector(".watch")?.getAttribute("href")).toBe(
      "https://twitch.tv/karssi",
    );
  });

  it("still renders its casters for a server that sends no languages yet", () => {
    // During a deploy the new page can meet the old server's payload.
    const match = live(stage("group_h"));
    match.race!.race.casters = [
      { id: "c1", user: person("karssi"), is_live: false, stream_url: null },
    ];
    const { getByText } = render(EventLiveMatches, {
      matches: [match],
      stages: [],
      now: NOW,
    });
    expect(getByText("karssi")).toBeTruthy();
  });
});
