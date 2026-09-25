import { describe, expect, it, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import RunnerCard from "$lib/components/cast/RunnerCard.svelte";
import { rewards } from "$lib/stores/rewards.svelte";

const baseProps = {
  rank: 1,
  avatarUrl: null,
  totalLayers: 10,
  rect: { x: 0, y: 0, w: 280, h: 360 },
  variant: "card" as const,
  leader: false,
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

/** The Gap row's value cell: `.crow` pairs a `.ck` label with a `.cv` value,
 * and the four rows (Depth, Gap, Deaths, IGT) share the `.cv` class, so a
 * plain `.cv` selector can't tell them apart. */
function gapValueCell(container: HTMLElement): Element | null {
  for (const row of container.querySelectorAll(".crow")) {
    if (row.querySelector(".ck")?.textContent === "Gap") {
      return row.querySelector(".cv");
    }
  }
  return null;
}

describe("RunnerCard: gap row", () => {
  it("shows nothing, not a placeholder, for the leader (gap_ms null)", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        leader: true,
        participant: fakeParticipant({ status: "playing", gap_ms: null }),
      },
    });
    const cell = gapValueCell(container);
    expect(cell).not.toBeNull();
    // Empty, not "-", not "--.--", not the mockup's em dash.
    expect(cell?.textContent).toBe("");
  });

  it("reads DNF for an abandoned runner", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ status: "abandoned", gap_ms: null }),
      },
    });
    const cell = gapValueCell(container);
    expect(cell?.textContent).toBe("DNF");
    expect(cell?.classList.contains("dnf")).toBe(true);
  });

  it("renders the signed value with the behind colour for a runner behind", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ status: "playing", gap_ms: 12_345 }),
      },
    });
    const cell = gapValueCell(container);
    expect(cell?.textContent).toBe("+0:12");
    expect(cell?.classList.contains("behind")).toBe(true);
    expect(cell?.classList.contains("ahead")).toBe(false);
  });

  it("renders the signed value with the ahead colour for a runner ahead", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ status: "playing", gap_ms: -8_000 }),
      },
    });
    const cell = gapValueCell(container);
    expect(cell?.textContent).toBe("-0:08");
    expect(cell?.classList.contains("ahead")).toBe(true);
    expect(cell?.classList.contains("behind")).toBe(false);
  });

  it("keeps a finished non-leader's real gap instead of DNF", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ status: "finished", gap_ms: 5_000 }),
      },
    });
    const cell = gapValueCell(container);
    expect(cell?.textContent).toBe("+0:05");
  });
});

describe("RunnerCard: name template", () => {
  beforeEach(() => {
    rewards.catalog = null;
  });

  it("carries the Pioneer template's serif family through the style binding", () => {
    // The exact name_css shipped for "pioneer" (server/speedfog_racing/rewards/catalog.py):
    // double-quoted "Times New Roman" inside the CSS value. Built as an HTML
    // string instead of bound via Svelte's style={...}, this double quote
    // would close the attribute early and silently drop the rest of the
    // style, which is exactly the bug this test pins.
    rewards.catalog = {
      badges: [],
      name_templates: [
        {
          id: "pioneer",
          name: "Pioneer",
          color: null,
          gradient: null,
          name_css:
            'font-family: Georgia, "Times New Roman", Times, serif; font-style: italic;',
          background_css: null,
          sort_order: 30,
        },
      ],
      phantom_skins: [],
    };
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ equipped_name_template_id: "pioneer" }),
      },
    });
    const name = container.querySelector(".cname");
    expect(name?.getAttribute("style") ?? "").toContain("Times New Roman");
  });
});

describe("RunnerCard: splits (tall variant)", () => {
  it("renders each split's zone and duration as a plain time, not a signed gap", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        variant: "tall",
        participant: fakeParticipant(),
        splits: [
          { zone: "Liurnia of the Lakes", durationMs: 125_000 },
          { zone: "Stormveil Castle", durationMs: 45_000 },
        ],
      },
    });
    const rows = Array.from(container.querySelectorAll(".sp-r"));
    expect(rows.map((r) => r.querySelector("b")?.textContent)).toEqual([
      "Liurnia of the Lakes",
      "Stormveil Castle",
    ]);
    // A duration reads like IGT (2:05), never a signed gap (+2:05 or -2:05):
    // a split is time spent in a finished zone, not an offset to the leader.
    expect(rows.map((r) => r.querySelector("i")?.textContent)).toEqual([
      "2:05",
      "0:45",
    ]);
  });

  it("renders no splits section for the card and mirror variants", () => {
    const { container } = render(RunnerCard, {
      props: {
        ...baseProps,
        variant: "card",
        participant: fakeParticipant(),
        splits: [{ zone: "Liurnia of the Lakes", durationMs: 125_000 }],
      },
    });
    expect(container.querySelector(".splits")).toBeNull();
  });
});
