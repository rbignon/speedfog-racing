import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import type { RaceDetail } from "$lib/api";

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

  it("says Finished in large type once the race is over", () => {
    const { container } = renderDesk(fakeRace({ status: "finished" }));
    const zone = container.querySelector(".clock-zone");
    expect(zone?.querySelector(".cz-state")?.textContent).toBe("Finished");
    expect(zone?.querySelector(".cz-big")).toBeNull();
  });
});
