import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastMiniStandings from "$lib/components/cast/CastMiniStandings.svelte";

const baseProps = {
  totalLayers: 10,
  rect: { x: 0, y: 0, w: 320, h: 148 },
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
  return container.querySelectorAll(".lrow")[i]?.querySelector(".gap") ?? null;
}

describe("CastMiniStandings: row cap", () => {
  // baseProps.rect is 320x148, the real FOCUS_STANDINGS rect from layout.ts:
  // (148 - 10 chrome reserve) / 33 row height = 4 rows fit.
  function participants(n: number) {
    return Array.from({ length: n }, (_, i) =>
      fakeParticipant({ id: `p-${i}`, twitch_username: `runner${i}` }),
    );
  }

  it("shows every row and no overflow line when the field fits under capacity", () => {
    const { container } = render(CastMiniStandings, {
      props: { ...baseProps, participants: participants(2) },
    });
    expect(container.querySelectorAll(".lrow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".lrow")).toHaveLength(2);
  });

  it("shows every row and no overflow line when the field exactly fills capacity", () => {
    const { container } = render(CastMiniStandings, {
      props: { ...baseProps, participants: participants(4) },
    });
    expect(container.querySelectorAll(".lrow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".lrow")).toHaveLength(4);
  });

  it("caps rows and reports the rest once the field exceeds capacity, never overflowing the panel", () => {
    const { container } = render(CastMiniStandings, {
      props: { ...baseProps, participants: participants(13) },
    });
    const rows = container.querySelectorAll(".lrow");
    expect(rows).toHaveLength(4); // 3 data rows + 1 overflow row
    const more = container.querySelector(".lrow.more .more-text");
    expect(more?.textContent).toBe("+ 10 more");
  });
});

describe("CastMiniStandings: gap column", () => {
  it("shows nothing, not a placeholder, for the leader (gap_ms null)", () => {
    const { container } = render(CastMiniStandings, {
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
    const { container } = render(CastMiniStandings, {
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
    const { container } = render(CastMiniStandings, {
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
    const { container } = render(CastMiniStandings, {
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
