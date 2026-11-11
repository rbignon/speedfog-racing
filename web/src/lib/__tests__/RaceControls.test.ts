import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import RaceControls from "$lib/components/RaceControls.svelte";
import {
  rerollSeed,
  type AuthUser,
  type RaceDetail,
  type RunMode,
} from "$lib/api";
import { auth } from "$lib/stores/auth.svelte";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, rerollSeed: vi.fn() };
});

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
    unranked_reason: null,
    unranked_code: null,
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

  async function openReroll(r: RaceDetail) {
    const view = mount(r, "setup");
    const reroll = [...view.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Re-roll Seed"),
    )!;
    await fireEvent.click(reroll);
    return view;
  }

  describe("on a speedrun race", () => {
    beforeEach(() => {
      vi.mocked(rerollSeed).mockReset();
      vi.mocked(rerollSeed).mockResolvedValue(race("speedrun"));
    });

    function confirmButton(container: HTMLElement): HTMLButtonElement {
      return [...container.querySelectorAll(".actions button")].find((b) =>
        b.textContent?.includes("Re-roll"),
      ) as HTMLButtonElement;
    }

    it("always reports the seed, so the race never leaves the boards", async () => {
      const { queryByLabelText } = await openReroll(race("speedrun"));
      expect(queryByLabelText("Report this seed as buggy")).toBeNull();
      expect(queryByLabelText("Reason for the re-roll")).not.toBeNull();
    });

    it("promises the boards only to a race that still counts", async () => {
      const KEEPS = /keeps counting on the Speedrun boards/;
      const counting = await openReroll(race("speedrun"));
      expect(counting.queryByText(KEEPS)).not.toBeNull();
      counting.unmount();

      const off = await openReroll(
        race("speedrun", {
          unranked_code: "rerolled",
          unranked_reason: "Re-rolled race: ...",
        }),
      );
      expect(off.queryByText(KEEPS)).toBeNull();
      expect(
        off.queryByText(/goes to the admins as a seed report/),
      ).not.toBeNull();
    });

    it.each(["", "   "])(
      "keeps the window open without a reason (%j)",
      async (reason) => {
        const { container, getByLabelText, queryByText } = await openReroll(
          race("speedrun"),
        );
        await fireEvent.input(getByLabelText("Reason for the re-roll"), {
          target: { value: reason },
        });
        await fireEvent.click(confirmButton(container));

        expect(queryByText("A reason is required.")).not.toBeNull();
        expect(getByLabelText("Reason for the re-roll")).not.toBeNull();
        expect(rerollSeed).not.toHaveBeenCalled();
      },
    );

    it("sends the trimmed reason as a seed report", async () => {
      const { container, getByLabelText } = await openReroll(race("speedrun"));
      await fireEvent.input(getByLabelText("Reason for the re-roll"), {
        target: { value: "  Softlock at the start  " },
      });
      await fireEvent.click(confirmButton(container));

      expect(rerollSeed).toHaveBeenCalledWith(
        "race-1",
        true,
        "Softlock at the start",
      );
    });
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

describe("RaceControls: Start Race", () => {
  afterEach(() => {
    auth.user = null;
  });

  function startButton(
    role: string,
    participants: number,
    lateJoin: number | null,
  ): HTMLButtonElement {
    auth.user = { id: "u1", role } as unknown as AuthUser;
    const r = race("speedrun", {
      seeds_released_at: "2026-11-06T10:00:00Z",
      late_join_window_minutes: lateJoin,
      participants: Array.from({ length: participants }, (_, i) => ({
        id: `p${i}`,
      })),
    } as Partial<RaceDetail>);
    const { container } = mount(r, "setup");
    return [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Start Race"),
    )!;
  }

  it.each([
    // The late-join bet: start alone, the field joins the running race.
    ["trusted", 1, 30],
    ["admin", 0, null],
  ])(
    "lets role %s start with %i participant(s) and window %s",
    (role, participants, lateJoin) => {
      const button = startButton(role, participants, lateJoin);
      expect(button.disabled).toBe(false);
      expect(button.title).toBe("");
    },
  );

  it.each([
    // Nobody could join a running race without a window.
    ["trusted", 1, null, "required without a late-join window"],
    ["trusted", 0, 30, "At least 1 participant required"],
    // Starting alone is a trusted right, not an organizer one.
    ["organizer", 1, 30, "At least 2 participants required"],
  ])(
    "keeps role %s with %i participant(s) and window %s waiting",
    (role, participants, lateJoin, hint) => {
      const button = startButton(role, participants, lateJoin);
      expect(button.disabled).toBe(true);
      expect(button.title).toContain(hint);
    },
  );
});
