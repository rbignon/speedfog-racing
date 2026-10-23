import { describe, expect, it } from "vitest";
import { endHeadline, introClock } from "$lib/cast/slates";
import type { EventStageEntry } from "$lib/api";

describe("introClock", () => {
  const START = "2026-10-24T19:00:00Z";
  const startMs = Date.parse(START);

  // Rounded up like the race scenes' own start countdown: 12:35 still reads
  // until the 12:34 second actually begins.
  it("counts down to a stage whose time is set", () => {
    expect(introClock(START, true, startMs - 754_500)).toEqual({
      label: "Starts in",
      text: "12:35",
    });
  });

  it("says the start is near once the countdown runs out", () => {
    for (const now of [startMs, startMs + 60_000]) {
      expect(introClock(START, true, now)).toEqual({
        label: null,
        text: "Starting soon",
      });
    }
  });

  // A day-only date stands at noon UTC: counting down to it would announce
  // a start nobody set.
  it("shows the day alone while only the day is set", () => {
    expect(
      introClock("2026-11-01T12:00:00Z", false, startMs - 3_600_000),
    ).toEqual({ label: null, text: "Sun 1 Nov" });
  });

  it("shows nothing without a date", () => {
    expect(introClock(null, false, startMs)).toBeNull();
  });
});

function entry(name: string, points: number, advances = false) {
  return {
    user: { id: name, twitch_username: name, twitch_display_name: name },
    points,
    advances,
  } as unknown as EventStageEntry;
}

describe("endHeadline", () => {
  const results = [entry("ana", 270), entry("bob", 210), entry("cid", 150)];
  const names = (h: ReturnType<typeof endHeadline>) =>
    h.runners.map((r) => [r.entry.user.twitch_username, r.next]);

  // The same cut the standings panel draws its advancing mark at, so the
  // slate's hero and the panel under it never disagree.
  it("puts the runners above the cut up front while the stage is raced", () => {
    const h = endHeadline(
      { kind: "round", advance: 2, complete: false, settled_results: results },
      ["Quarter A", "Quarter B"],
    );
    expect(h.title).toBe("Qualified");
    expect(h.provisional).toBe(true);
    expect(names(h)).toEqual([
      ["ana", "Quarter A"],
      ["bob", "Quarter B"],
    ]);
  });

  it("follows the server's verdict once the stage is complete", () => {
    const h = endHeadline(
      {
        kind: "round",
        advance: 2,
        complete: true,
        settled_results: [
          entry("ana", 270, true),
          entry("bob", 210, false),
          entry("cid", 150, true),
        ],
      },
      ["Quarter A", "Quarter B"],
    );
    expect(h.provisional).toBe(false);
    expect(names(h)).toEqual([
      ["ana", "Quarter A"],
      ["cid", null],
    ]);
  });

  it("crowns the final's winner alone", () => {
    const h = endHeadline(
      {
        kind: "final",
        advance: null,
        complete: true,
        settled_results: results,
      },
      [],
    );
    expect(h.title).toBe("Champion");
    expect(names(h)).toEqual([["ana", null]]);
  });

  it("names a showcase's winner alone, nobody going on from it", () => {
    const h = endHeadline(
      {
        kind: "showcase",
        advance: null,
        complete: false,
        settled_results: results,
      },
      [],
    );
    expect(h.title).toBe("Winner");
    expect(names(h)).toEqual([["ana", null]]);
  });

  it("has nobody to show and nothing provisional before the first result", () => {
    const h = endHeadline(
      { kind: "round", advance: 2, complete: false, settled_results: [] },
      ["Quarter A", "Quarter B"],
    );
    expect(h.runners).toEqual([]);
    expect(h.provisional).toBe(false);
  });
});
