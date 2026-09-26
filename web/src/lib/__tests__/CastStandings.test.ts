import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastStandings from "$lib/components/cast/CastStandings.svelte";

const baseProps = {
  totalLayers: 10,
  rect: { x: 0, y: 0, w: 972, h: 230 },
};

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    status: "playing",
    current_zone: null,
    current_layer: 3,
    igt_ms: 90_000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    gap_ms: null,
    equipped_badge_id: null,
    equipped_name_template_id: null,
    ...over,
  };
}

/** The gap cell of the row at index `i` (rows are rendered in the order
 * `participants` is given, matching the already rank-ordered leaderboard). */
function gapCell(container: HTMLElement, i: number): Element | null {
  return container.querySelectorAll(".rrow")[i]?.querySelector(".gap") ?? null;
}

describe("CastStandings: gap column", () => {
  it("shows nothing, not a placeholder, for the leader (gap_ms null)", () => {
    const { container } = render(CastStandings, {
      props: {
        ...baseProps,
        participants: [fakeParticipant({ id: "p-1", gap_ms: null })],
      },
    });
    const cell = gapCell(container, 0);
    expect(cell).not.toBeNull();
    expect(cell?.textContent).toBe("");
  });

  it("reads DNF for an abandoned runner", () => {
    const { container } = render(CastStandings, {
      props: {
        ...baseProps,
        participants: [
          fakeParticipant({ id: "p-1", gap_ms: null }),
          fakeParticipant({
            id: "p-2",
            status: "abandoned",
            gap_ms: null,
          }),
        ],
      },
    });
    const cell = gapCell(container, 1);
    expect(cell?.textContent).toBe("DNF");
    expect(cell?.classList.contains("dnf")).toBe(true);
  });

  it("renders the signed value with the behind colour for a runner behind", () => {
    const { container } = render(CastStandings, {
      props: {
        ...baseProps,
        participants: [
          fakeParticipant({ id: "p-1", gap_ms: null }),
          fakeParticipant({ id: "p-2", gap_ms: 12_345 }),
        ],
      },
    });
    const cell = gapCell(container, 1);
    expect(cell?.textContent).toBe("+0:12");
    expect(cell?.classList.contains("behind")).toBe(true);
    expect(cell?.classList.contains("ahead")).toBe(false);
  });

  it("renders the signed value with the ahead colour for a runner ahead", () => {
    const { container } = render(CastStandings, {
      props: {
        ...baseProps,
        participants: [
          fakeParticipant({ id: "p-1", gap_ms: null }),
          fakeParticipant({ id: "p-2", gap_ms: -8_000 }),
        ],
      },
    });
    const cell = gapCell(container, 1);
    expect(cell?.textContent).toBe("-0:08");
    expect(cell?.classList.contains("ahead")).toBe(true);
    expect(cell?.classList.contains("behind")).toBe(false);
  });
});

describe("CastStandings: row cap", () => {
  // baseProps.rect is 972x230, the real METRO_STANDINGS rect from layout.ts:
  // (230 - 32 title reserve) / 45 row height = 4 rows per column, two
  // columns wide (the zone column is gone, so there's no row spent on an
  // overflow line either): 8 total.
  function participants(n: number) {
    return Array.from({ length: n }, (_, i) =>
      fakeParticipant({ id: `p-${i}`, twitch_username: `runner${i}` }),
    );
  }

  it("shows every row and no overflow line when the field fits under capacity", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(2) },
    });
    expect(container.querySelector(".title-more")).toBeNull();
    expect(container.querySelectorAll(".rrow")).toHaveLength(2);
  });

  it("shows every row and no overflow line when the field exactly fills capacity", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(8) },
    });
    expect(container.querySelector(".title-more")).toBeNull();
    expect(container.querySelectorAll(".rrow")).toHaveLength(8);
  });

  it("caps rows and reports the rest on the title line once the field exceeds capacity", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(13) },
    });
    // capacity 8, every one of them a data row: the overflow count moves to
    // the title line instead of spending a row on it.
    const rows = container.querySelectorAll(".rrow");
    expect(rows).toHaveLength(8);
    expect(container.querySelector(".title-more")?.textContent).toBe(
      "+ 5 more",
    );
  });

  it("reads down the first column then down the second", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(13) },
    });
    const columns = container.querySelectorAll(".columns .column");
    expect(columns).toHaveLength(2);
    const ranksIn = (col: Element) =>
      [...col.querySelectorAll(".rk")].map((el) => el.textContent);
    expect(ranksIn(columns[0])).toEqual(["1", "2", "3", "4"]);
    expect(ranksIn(columns[1])).toEqual(["5", "6", "7", "8"]);
  });

  it("lets a caster's lines override show fewer rows than the panel fits", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(13), lines: 3 },
    });
    expect(container.querySelectorAll(".rrow")).toHaveLength(3);
    expect(container.querySelector(".title-more")?.textContent).toBe(
      "+ 10 more",
    );
  });

  it("never lets a caster's lines override exceed what the panel actually fits", () => {
    const { container } = render(CastStandings, {
      props: { ...baseProps, participants: participants(13), lines: 100 },
    });
    expect(container.querySelectorAll(".rrow")).toHaveLength(8); // same cap as no override at all
    expect(container.querySelector(".title-more")?.textContent).toBe(
      "+ 5 more",
    );
  });
});
