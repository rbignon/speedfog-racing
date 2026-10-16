import { describe, expect, it } from "vitest";
import type { EventFieldSlot, RaceDetail } from "$lib/api";
import {
  obsFileName,
  raceSeats,
  stageFieldSettled,
  stageSeats,
} from "$lib/cast/obs-export";
import type { ObsRunner } from "$lib/cast/obs";

function user(username: string, display: string | null = null) {
  return {
    id: `u-${username}`,
    twitch_username: username,
    twitch_display_name: display,
    twitch_avatar_url: null,
  };
}

function seat(
  username: string | null,
  over: Partial<EventFieldSlot> = {},
): EventFieldSlot {
  return {
    user: username ? user(username) : null,
    label: "1st of Group A",
    forfeited: false,
    source: null,
    place: null,
    ...over,
  };
}

function race(over: Partial<RaceDetail> = {}): RaceDetail {
  return {
    id: "1234abcd-0000-4000-8000-000000000000",
    event_slug: null,
    event_slot: null,
    participants: [],
    ...over,
  } as unknown as RaceDetail;
}

function participant(username: string, colorIndex: number, display = "") {
  return { user: user(username, display || null), color_index: colorIndex };
}

const logins = (seats: (ObsRunner | null)[]) =>
  seats.map((s) => s?.username ?? null);

describe("stageSeats", () => {
  it("stage seats follow the field order, pins on top", () => {
    const field = ["a", "b", "c", "d"].map((n) => seat(n));
    expect(logins(stageSeats(field, [null, "d", null, null]))).toEqual([
      "a",
      "d",
      "b",
      "c",
    ]);
  });

  it("an unsettled seat seats nobody", () => {
    const field = [seat("a"), seat(null), seat("c"), seat("d")];
    expect(logins(stageSeats(field, [null, null, null, null]))).toEqual([
      "a",
      "c",
      "d",
      null,
    ]);
    expect(stageFieldSettled(field)).toBe(false);
    expect(stageFieldSettled(field.map((s) => (s.user ? s : seat("b"))))).toBe(
      true,
    );
  });

  it("a forfeited seat seats nobody, yet the field is settled", () => {
    // Withdrew after the lock: the seat stays theirs and nobody replaces
    // them, so they race no race of the stage and get no POV.
    const field = [
      seat("a"),
      seat("b", { forfeited: true }),
      seat("c"),
      seat("d"),
    ];
    expect(logins(stageSeats(field, [null, null, null, null]))).toEqual([
      "a",
      "c",
      "d",
      null,
    ]);
    expect(stageFieldSettled(field)).toBe(true);
  });
});

describe("raceSeats", () => {
  it("race seats match the panel's auto labels", () => {
    // Participants come ranked, not in join order: the silent holes seat by
    // color_index, as the scenes (and the panel's "(auto: ...)") do.
    const r = race({
      participants: [
        participant("carol", 2),
        participant("alice", 0, "Alice"),
        participant("dave", 3),
        participant("bob", 1),
      ],
    } as Partial<RaceDetail>);

    expect(raceSeats(r, [null, null, null, null])).toEqual([
      { username: "alice", name: "Alice" },
      { username: "bob", name: "bob" },
      { username: "carol", name: "carol" },
      { username: "dave", name: "dave" },
    ]);
    expect(logins(raceSeats(r, [null, "dave", null, null]))).toEqual([
      "alice",
      "dave",
      "bob",
      "carol",
    ]);
  });
});

describe("obsFileName", () => {
  it("file names", () => {
    const staged = race({ event_slug: "season-one", event_slot: "group_g:2" });
    expect(obsFileName("match", staged)).toBe(
      "speedfog-season-one-group_g.json",
    );
    expect(obsFileName("race", staged)).toBe(
      "speedfog-season-one-group_g-2.json",
    );
    for (const slot of [null, "qualifier:standard:3"]) {
      expect(
        obsFileName(
          "race",
          race({ event_slug: slot ? "season-one" : null, event_slot: slot }),
        ),
      ).toBe("speedfog-race-1234abcd.json");
    }
  });
});
