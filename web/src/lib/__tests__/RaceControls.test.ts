import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import RaceControls from "$lib/components/RaceControls.svelte";
import type { RaceDetail, RunMode } from "$lib/api";

function race(mode: RunMode, extra: Partial<RaceDetail> = {}): RaceDetail {
  return {
    id: "race-1",
    mode,
    daily_date: null,
    event_id: null,
    seeds_released_at: null,
    is_public: true,
    open_registration: false,
    max_participants: null,
    participants: [],
    ...extra,
  } as unknown as RaceDetail;
}

function mount(r: RaceDetail, raceStatus: string) {
  return render(RaceControls, {
    props: {
      race: r,
      raceStatus,
      onRaceUpdated: () => {},
      onDeleteRace: () => {},
    },
  });
}

function hasButton(container: HTMLElement, label: string): boolean {
  return [...container.querySelectorAll("button")].some((b) =>
    b.textContent?.includes(label),
  );
}

async function openMenu(container: HTMLElement) {
  await fireEvent.click(container.querySelector(".dropdown-menu .trigger")!);
}

describe("RaceControls: Re-roll Seed", () => {
  it("is offered on a normal race in setup", () => {
    const { container } = mount(race("normal"), "setup");
    expect(hasButton(container, "Re-roll Seed")).toBe(true);
  });

  it.each(["setup", "running", "finished"])(
    "is never offered on a Set Seed race (%s)",
    (status) => {
      const released = race("set_seed", {
        seeds_released_at: "2026-10-30T10:00:00Z",
      });
      const { container } = mount(released, status);
      expect(hasButton(container, "Re-roll Seed")).toBe(false);
    },
  );

  it("stays on a running daily", () => {
    const { container } = mount(
      race("normal", { daily_date: "2026-10-30" }),
      "running",
    );
    expect(hasButton(container, "Re-roll Seed")).toBe(true);
  });
});

describe("RaceControls: Reset Race", () => {
  it.each(["running", "finished"])(
    "is offered on a normal race (%s)",
    async (status) => {
      const { container } = mount(race("normal"), status);
      await openMenu(container);
      expect(hasButton(container, "Reset Race")).toBe(true);
    },
  );

  it("is offered on a Set Seed race", async () => {
    const { container } = mount(race("set_seed"), "finished");
    await openMenu(container);
    expect(hasButton(container, "Reset Race")).toBe(true);
  });

  it.each([
    ["a community race", race("normal"), true],
    ["an event race", race("normal", { event_id: "event-1" }), false],
    ["a Set Seed race", race("set_seed"), false],
  ])(
    "says whether resetting %s keeps it off the Speedrun boards",
    async (_label, r, warned) => {
      const { container, getByText } = mount(r, "finished");
      await openMenu(container);
      const reset = [...container.querySelectorAll("button")].find((b) =>
        b.textContent?.includes("Reset Race"),
      )!;
      await fireEvent.click(reset);
      expect(
        getByText(/^Reset this race\?/).textContent?.includes("Speedrun board"),
      ).toBe(warned);
    },
  );

  it.each(["running", "finished"])(
    "is not offered on a speedrun race (%s)",
    async (status) => {
      const { container } = mount(race("speedrun"), status);
      await openMenu(container);
      expect(hasButton(container, "Disqualify a runner...")).toBe(true);
      expect(hasButton(container, "Reset Race")).toBe(false);
    },
  );
});
