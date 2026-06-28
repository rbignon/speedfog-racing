import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Leaderboard from "$lib/components/Leaderboard.svelte";

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    twitch_avatar_url: null,
    status: "finished",
    current_zone: null,
    current_layer: 0,
    igt_ms: 1500,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: [],
    daily_points: 50,
    ...over,
  };
}

describe("Leaderboard: +XX indicator (finished mode)", () => {
  it("renders +XX in the top-right slot when daily_points is set", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: 33 })],
        mode: "finished",
        showRunDetails: true,
      },
    });
    const indicator = container.querySelector(".points-earned");
    expect(indicator?.textContent ?? "").toMatch(/\+33/);
  });

  it("does not render +XX when daily_points is null", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: null })],
        mode: "finished",
        showRunDetails: true,
      },
    });
    const indicator = container.querySelector(".points-earned");
    expect(indicator).toBeNull();
  });

  it("renders +XX for a qualified abandoner and moves the layer to the Abandoned line", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [
          fakeParticipant({
            status: "abandoned",
            current_layer: 11,
            daily_points: 7,
          }),
        ],
        mode: "finished",
        totalLayers: 12,
        showRunDetails: true,
      },
    });
    // Points take the top-right slot, even for abandoners.
    expect(
      container.querySelector(".points-earned")?.textContent ?? "",
    ).toMatch(/\+7/);
    // The layer fraction is no longer in the top-right slot...
    expect(container.querySelector(".layer-fraction")).toBeNull();
    // ...it sits on the Abandoned line instead.
    expect(
      container.querySelector(".abandoned-label")?.textContent ?? "",
    ).toMatch(/Abandoned.*12\/12/s);
  });

  it("keeps the ✓ behavior in running mode", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: null })],
        mode: "running",
        showRunDetails: true,
      },
    });
    const check = container.querySelector(".finish-icon");
    expect(check?.textContent ?? "").toContain("✓");
  });
});

describe("Leaderboard: clear-selection pill", () => {
  it("renders the pill with the selected count when there is a selection", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set(["p-1"]),
        onClearSelection: () => {},
      },
    });
    const pill = container.querySelector(".clear-pill");
    expect(pill).not.toBeNull();
    expect(pill?.querySelector(".count")?.textContent).toBe("1");
  });

  it("does not render the pill when selection is empty", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set<string>(),
        onClearSelection: () => {},
      },
    });
    expect(container.querySelector(".clear-pill")).toBeNull();
  });
});

describe("Leaderboard: select-box checkbox", () => {
  it("hides the checkboxes until at least one player is selected", () => {
    const empty = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set<string>(),
        onToggle: () => {},
      },
    });
    expect(empty.container.querySelector(".select-box")).toBeNull();

    // Once something is selected, every row exposes its checkbox.
    const withSelection = render(Leaderboard, {
      props: {
        participants: [fakeParticipant(), fakeParticipant({ id: "p-2" })],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set(["p-1"]),
        onToggle: () => {},
      },
    });
    expect(
      withSelection.container.querySelectorAll(".select-box"),
    ).toHaveLength(2);
  });

  it("toggles a row additively (ctrl-style) without firing the row's single-select", async () => {
    const onToggle = vi.fn();
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant(), fakeParticipant({ id: "p-2" })],
        mode: "running",
        showRunDetails: true,
        // p-1 already selected, so the checkboxes are visible.
        selectedIds: new Set(["p-1"]),
        onToggle,
      },
    });
    // Click the unselected row's box to add it to the comparison.
    const box = container.querySelector(".select-box:not(.checked)");
    expect(box).not.toBeNull();
    await fireEvent.click(box!);
    // stopPropagation keeps the row's onclick from also firing, so the
    // callback is invoked exactly once, with the additive (ctrlKey) flag.
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith("p-2", true);
  });

  it("single-selects via a row-body click (ctrlKey false), distinct from the checkbox", async () => {
    const onToggle = vi.fn();
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set<string>(),
        onToggle,
      },
    });
    await fireEvent.click(container.querySelector(".participant")!);
    // Row body is the single-select path: no additive flag.
    expect(onToggle).toHaveBeenCalledWith("p-1", false);
  });

  it("marks the box checked for selected participants", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set(["p-1"]),
        onToggle: () => {},
      },
    });
    expect(container.querySelector(".select-box.checked")).not.toBeNull();
  });
});

describe("Leaderboard: gap visibility in selection mode", () => {
  it("shows the gap normally but hides it once a selection is active", () => {
    // Selection mode narrows the row (select-boxes appear), so the gap is
    // dropped to keep the row readable.
    const noSelection = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ gap_ms: 49_000 })],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set<string>(),
        onToggle: () => {},
      },
    });
    expect(noSelection.container.querySelector(".gap")).not.toBeNull();

    const withSelection = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ gap_ms: 49_000 })],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set(["p-1"]),
        onToggle: () => {},
      },
    });
    expect(withSelection.container.querySelector(".gap")).toBeNull();
  });
});
