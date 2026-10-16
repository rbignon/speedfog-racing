import { describe, expect, it } from "vitest";
import type { EventFieldSlot, RaceDetail } from "$lib/api";
import {
  duelHoleSeats,
  obsFileName,
  raceSeats,
  stageFieldSettled,
  stageFieldSize,
  stageSeats,
} from "$lib/cast/obs-export";
import type { ObsRunner } from "$lib/cast/obs";
import { NO_RUNNER } from "$lib/events";

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

  it("a seat nobody will fill seats nobody, yet the field is settled", () => {
    // A fed seat its finished source stage could not fill, or a seeded seat
    // past the end of a final ladder: empty for good, nothing to wait for.
    const field = [
      seat("a"),
      seat(null, { label: NO_RUNNER }),
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

describe("stageFieldSize", () => {
  it("counts the seats that will race", () => {
    const five = ["a", "b", "c", "d", "e"].map((n) => seat(n));
    expect(stageFieldSize(five)).toBe(5);
    // A forfeited runner and a seat nobody will fill race nothing...
    const withForfeit = five.map((s, i) =>
      i === 1 ? { ...s, forfeited: true } : s,
    );
    expect(stageFieldSize(withForfeit)).toBe(4);
    const withNoRunner = five.map((s, i) =>
      i === 3 ? seat(null, { label: NO_RUNNER }) : s,
    );
    expect(stageFieldSize(withNoRunner)).toBe(4);
    // ...but a seat still waiting for its runner will.
    const withUndecided = five.map((s, i) => (i === 2 ? seat(null) : s));
    expect(stageFieldSize(withUndecided)).toBe(5);
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

describe("duelHoleSeats", () => {
  // The duel holes read POV 1 and 2's pins alone: alice, pinned in POV 3,
  // is the first runner nobody pinned there, so the duel seats her in POV 1
  // where the four-seat resolution has her in POV 3.
  it("resolves the duel holes over POV 1 and 2's pins alone", () => {
    const pins = [null, null, "alice", null];
    const r = race({
      participants: ["alice", "bob", "carol", "dave", "erin"].map((n, i) =>
        participant(n, i),
      ),
    } as Partial<RaceDetail>);
    expect(logins(raceSeats(r, pins).slice(0, 2))).toEqual(["bob", "carol"]);
    expect(logins(duelHoleSeats((p) => raceSeats(r, p), pins))).toEqual([
      "alice",
      "bob",
    ]);
    const field = ["alice", "bob", "carol", "dave", "erin"].map((n) => seat(n));
    expect(logins(duelHoleSeats((p) => stageSeats(field, p), pins))).toEqual([
      "alice",
      "bob",
    ]);
    expect(
      logins(duelHoleSeats((p) => raceSeats(r, p), ["dave", null, "alice"])),
    ).toEqual(["dave", "alice"]);
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
