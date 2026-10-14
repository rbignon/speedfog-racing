import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastRoundStandings from "$lib/components/cast/CastRoundStandings.svelte";
import type { EventStageEntry, User } from "$lib/api";

const baseProps = {
  rect: { x: 0, y: 0, w: 484, h: 412 },
  label: "Semi B",
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
  // talk scene: (412 - 74 header reserve) / 56 row height = 6 rows fit.
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
      props: { ...baseProps, results: results(6) },
    });
    expect(container.querySelectorAll(".srow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".srow")).toHaveLength(6);
  });

  it("caps rows and reports the rest once the field exceeds capacity, never overflowing the panel", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, results: results(10) },
    });
    const rows = container.querySelectorAll(".srow");
    expect(rows).toHaveLength(6); // 5 data rows + 1 overflow row
    const more = container.querySelector(".srow.more .more-text");
    expect(more?.textContent).toBe("+ 5 more");
  });
});

describe("CastRoundStandings: advancing mark", () => {
  it("names each advancing runner's own next stage", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        nextLabels: ["Quarter A", "Quarter C"],
        advance: 2,
        complete: true,
        results: [
          fakeEntry({ user: fakeUser({ id: "u1" }), advances: true }),
          fakeEntry({ user: fakeUser({ id: "u2" }), advances: true }),
          fakeEntry({ user: fakeUser({ id: "u3" }), advances: false }),
        ],
      },
    });
    const tags = [...container.querySelectorAll(".stag")].map(
      (t) => t.textContent,
    );
    expect(tags).toEqual(["Quarter A", "Quarter C"]);
  });

  it("names the stage an advancing entry goes on to, and withholds chip and accent from the rest", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        nextLabels: ["Quarter A"],
        advance: 1,
        complete: true,
        results: [
          fakeEntry({ user: fakeUser({ id: "u1" }), advances: true }),
          fakeEntry({ user: fakeUser({ id: "u2" }), advances: false }),
        ],
      },
    });
    const rows = container.querySelectorAll(".srow");
    expect(rows[0].classList.contains("adv")).toBe(true);
    expect(rows[0].querySelector(".stag")?.textContent).toBe("Quarter A");
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
  it("calls the standings provisional while the stage is still raced", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, complete: false, results: [fakeEntry()] },
    });
    expect(container.querySelector(".seyebrow")?.textContent).toBe(
      "Provisional",
    );
  });

  it("calls them complete once the stage is over", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, complete: true, results: [fakeEntry()] },
    });
    expect(container.querySelector(".seyebrow")?.textContent).toBe("Complete");
  });

  it("says nothing before the first result, keeping its line", () => {
    const { container } = render(CastRoundStandings, {
      props: { ...baseProps, complete: false, results: [] },
    });
    expect(container.querySelector(".seyebrow")?.textContent).toBe("\u00a0");
  });
});

describe("CastRoundStandings: provisional qualifiers", () => {
  function results(n: number) {
    return Array.from({ length: n }, (_, i) =>
      fakeEntry({ user: fakeUser({ id: `u-${i}` }) }),
    );
  }

  function marks(container: Element) {
    return [...container.querySelectorAll(".srow:not(.more)")].map((row) => ({
      adv: row.classList.contains("adv"),
      tag: row.querySelector(".stag")?.textContent ?? null,
    }));
  }

  it("marks the runners above the cut while the stage runs, each with its place's next stage", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: results(4),
        advance: 2,
        complete: false,
        nextLabels: ["Quarter A", "Quarter C"],
      },
    });
    expect(marks(container)).toEqual([
      { adv: true, tag: "Quarter A" },
      { adv: true, tag: "Quarter C" },
      { adv: false, tag: null },
      { adv: false, tag: null },
    ]);
  });

  it("marks nobody on a stage nobody goes on from", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: results(4),
        advance: null,
        complete: false,
      },
    });
    expect(marks(container).some((m) => m.adv)).toBe(false);
  });

  // Pins the contract rather than a state the server sends today: once
  // complete, `advances` decides, so goesOn must not fall back to the row
  // order.
  it("follows the server's verdict once the stage is complete, not the row order", () => {
    const { container } = render(CastRoundStandings, {
      props: {
        ...baseProps,
        results: results(3),
        advance: 2,
        complete: true,
        nextLabels: ["Quarter A", "Quarter C"],
      },
    });
    expect(marks(container).some((m) => m.adv)).toBe(false);
  });
});
