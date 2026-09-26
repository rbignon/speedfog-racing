import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastRoundStandings from "$lib/components/cast/CastRoundStandings.svelte";
import type { EventStageEntry, User } from "$lib/api";

const baseProps = {
  rect: { x: 0, y: 0, w: 484, h: 412 },
  label: "Semi B",
  racesPlayed: 2,
  racesExpected: 3,
};

function fakeUser(over: Partial<User> = {}): User {
  return {
    id: "u-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    twitch_avatar_url: null,
    equipped_name_template_id: null,
    ...over,
  };
}

function fakeEntry(over: Partial<EventStageEntry> = {}): EventStageEntry {
  return {
    user: fakeUser(),
    newcomer: false,
    points: 100,
    igt_total: 0,
    advances: false,
    signature_weapon: null,
    ...over,
  };
}

describe("CastRoundStandings: row cap", () => {
  // baseProps.rect is 484x412, the real STANDINGS rect from layout.ts's
  // talk scene: (412 - 74 header reserve) / 72 row height = 4 rows fit.
  function results(n: number) {
    return Array.from({ length: n }, (_, i) =>
      fakeEntry({ user: fakeUser({ id: `u-${i}` }) }),
    );
  }

  it("shows every row and no overflow line when the field fits under capacity", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, results: results(2) },
    });
    expect(container.querySelectorAll(".srow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".srow")).toHaveLength(2);
  });

  it("shows every row and no overflow line when the field exactly fills capacity", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, results: results(4) },
    });
    expect(container.querySelectorAll(".srow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".srow")).toHaveLength(4);
  });

  it("caps rows and reports the rest once the field exceeds capacity, never overflowing the panel", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, results: results(10) },
    });
    const rows = container.querySelectorAll(".srow");
    expect(rows).toHaveLength(4); // 3 data rows + 1 overflow row
    const more = container.querySelector(".srow.more .more-text");
    expect(more?.textContent).toBe("+ 7 more");
  });
});

describe("CastRoundStandings: advancing mark", () => {
  it("gives an advancing entry the Final chip and row accent, and withholds both from the rest", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: [
          fakeEntry({ user: fakeUser({ id: "u1" }), advances: true }),
          fakeEntry({ user: fakeUser({ id: "u2" }), advances: false }),
        ],
      },
    });
    const rows = container.querySelectorAll(".srow");
    expect(rows[0].classList.contains("adv")).toBe(true);
    expect(rows[0].querySelector(".stag")?.textContent).toBe("Final");
    expect(rows[1].classList.contains("adv")).toBe(false);
    expect(rows[1].querySelector(".stag")).toBeNull();
  });
});

describe("CastRoundStandings: avatar", () => {
  it("falls back to an initial when the runner has no avatar", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: [
          fakeEntry({
            user: fakeUser({
              twitch_avatar_url: null,
              twitch_display_name: "Zara",
            }),
          }),
        ],
      },
    });
    expect(container.querySelector(".sav-placeholder")?.textContent).toBe("Z");
    expect(container.querySelector("img.sav")).toBeNull();
  });
});

describe("CastRoundStandings: rank", () => {
  it("numbers rows by their position in results, the server's own order, not by points", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: [
          fakeEntry({ user: fakeUser({ id: "u1" }), points: 50 }),
          fakeEntry({ user: fakeUser({ id: "u2" }), points: 175 }),
        ],
      },
    });
    const ranks = [...container.querySelectorAll(".srk")].map(
      (el) => el.textContent,
    );
    expect(ranks).toEqual(["1", "2"]);
  });
});

describe("CastRoundStandings: eyebrow", () => {
  it("reports races played against the stage's expected count", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, racesPlayed: 0, racesExpected: 3, results: [] },
    });
    expect(container.querySelector(".seyebrow")?.textContent).toBe(
      "After 0 of 3 races",
    );
  });
});
