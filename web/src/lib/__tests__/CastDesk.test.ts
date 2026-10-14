import { afterEach, describe, expect, it, vi } from "vitest";
import { flushSync } from "svelte";
import { render } from "@testing-library/svelte";
import type { RaceDetail } from "$lib/api";
import { raceStore } from "$lib/stores/race.svelte";

vi.mock("$app/state", () => ({
  page: { url: new URL("http://localhost/overlay/cast/race/r-1/quad") },
}));

const { default: CastDesk } =
  await import("$lib/components/cast/CastDesk.svelte");

function fakeRace(over: Record<string, unknown> = {}): RaceDetail {
  return {
    id: "r-1",
    name: "Group C - Race 2 - Boss Rush",
    status: "running",
    started_at: new Date(Date.now() - 15 * 60_000).toISOString(),
    race_ends_at: null,
    ...over,
  } as unknown as RaceDetail;
}

function renderDesk(race: RaceDetail) {
  return render(CastDesk, {
    props: {
      scene: "quad",
      race,
      cams: 2,
      casters: [null, null],
      partnerName: null,
    },
  });
}

afterEach(() => {
  raceStore.race = null;
  vi.useRealTimers();
});

describe("CastDesk: clock panel", () => {
  // One element per state: the ticking clock says the race is live on its
  // own, so it needs no Live tag; before and after, a word says the state.
  it("shows the running clock alone while the race runs", () => {
    const { container } = renderDesk(fakeRace());
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-big")?.textContent).toMatch(/^15:0\d$/);
    expect(zone?.textContent).not.toMatch(/live/i);
  });

  it("says Upcoming instead of a frozen 0:00 before the start", () => {
    const { container } = renderDesk(
      fakeRace({ status: "setup", started_at: null }),
    );
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-state")?.textContent).toBe("Upcoming");
    expect(zone?.querySelector(".cz-big")).toBeNull();
  });

  // The server runs the race from the start command on, its start
  // (`started_at`) a countdown later: until then the desk keeps its pre-start
  // word, with the time left under it, rather than a clock frozen at 0:00.
  it("keeps Upcoming with the time left during the start countdown", () => {
    const { container } = renderDesk(
      fakeRace({ started_at: new Date(Date.now() + 7_000).toISOString() }),
    );
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-state")?.textContent).toBe("Upcoming");
    expect(zone?.querySelector(".cz-end")?.textContent).toMatch(
      /^Starts in 0:0[78]$/,
    );
    expect(zone?.querySelector(".cz-big")).toBeNull();
  });

  it("counts a start arriving under a desk mounted long before from its full length", () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-14T19:00:00Z") });
    const { container } = renderDesk(
      fakeRace({ status: "setup", started_at: null }),
    );
    vi.setSystemTime(Date.parse("2026-10-14T19:45:00Z"));
    raceStore.race = {
      status: "running",
      started_at: "2026-10-14T19:45:10Z",
    } as unknown as typeof raceStore.race;
    flushSync();
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-end")?.textContent).toBe("Starts in 0:10");
    vi.advanceTimersByTime(10_010);
    flushSync();
    expect(zone?.querySelector(".cz-big")?.textContent).toBe("0:00");
  });

  it("shows the in-game cutoff under the clock, ahead of a wall-clock deadline", () => {
    const { container } = renderDesk(
      fakeRace({
        igt_cutoff_ms: 4_032_000,
        race_ends_at: new Date(Date.now() + 20 * 60_000).toISOString(),
      }),
    );
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-end")?.textContent).toBe(
      "IGT cutoff 1:07:12",
    );
  });

  it("says Finished in large type once the race is over", () => {
    const { container } = renderDesk(fakeRace({ status: "finished" }));
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-state")?.textContent).toBe("Finished");
    expect(zone?.querySelector(".cz-big")).toBeNull();
  });
});
