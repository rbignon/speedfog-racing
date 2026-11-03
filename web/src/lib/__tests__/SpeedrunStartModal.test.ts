import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    startSpeedrunSolo: vi.fn(),
    fetchFreshSpeedrunSeeds: vi.fn(),
    fetchSpeedrunSeedSummary: vi.fn(),
  };
});

import { goto } from "$app/navigation";
import SpeedrunStartModal from "$lib/components/stats/speedrun/SpeedrunStartModal.svelte";
import {
  fetchFreshSpeedrunSeeds,
  fetchSpeedrunSeedSummary,
  startSpeedrunSolo,
  type AuthUser,
  type SpeedrunSeedSummary,
  type TrainingSessionDetail,
} from "$lib/api";
import { auth } from "$lib/stores/auth.svelte";

const SEED = "363096a4243f";

function user(role: string): AuthUser {
  return {
    id: "u1",
    twitch_username: "runner",
    twitch_display_name: "Runner",
    twitch_avatar_url: null,
    role,
    locale: null,
    overlay_settings: null,
    feedback_prompted_at: null,
    race_count: 0,
    daily_count: 0,
    training_count: 0,
  };
}

function summary(over: Partial<SpeedrunSeedSummary> = {}): SpeedrunSeedSummary {
  return {
    seed_number: SEED,
    category: "standard",
    category_name: "Standard",
    replayable: true,
    not_replayable_reason: null,
    record: {
      igt_ms: 1_543_448,
      user: {
        id: "u9",
        twitch_username: "abisxoxo",
        twitch_display_name: "Abisxoxo",
        twitch_avatar_url: null,
      },
    },
    ...over,
  };
}

function renderWindow(
  props: {
    initialSeed?: string | null;
    pool?: string;
    retired?: boolean;
    recordSeed?: string | null;
  } = {},
) {
  return render(SpeedrunStartModal, {
    props: {
      pool: "standard",
      categoryName: "Standard",
      onClose: vi.fn(),
      ...props,
    },
  });
}

function text(el: Element | null): string {
  return el?.textContent?.replace(/\s+/g, " ").trim() ?? "";
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeEach(() => {
  auth.user = user("user");
  vi.mocked(goto).mockReset();
  vi.mocked(startSpeedrunSolo).mockReset();
  vi.mocked(fetchFreshSpeedrunSeeds).mockReset();
  vi.mocked(fetchFreshSpeedrunSeeds).mockResolvedValue({ fresh: true });
  vi.mocked(fetchSpeedrunSeedSummary).mockReset();
});

afterEach(() => {
  auth.user = null;
});

describe("Start a run: Random Seed", () => {
  it("starts a Speedrun solo run on the board's pool and opens it", async () => {
    vi.mocked(startSpeedrunSolo).mockResolvedValue({
      id: "s1",
    } as TrainingSessionDetail);
    renderWindow();

    const start = screen.getByRole("button", { name: "Start solo" });
    await waitFor(() =>
      expect((start as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(start);

    expect(fetchFreshSpeedrunSeeds).toHaveBeenCalledWith("standard");
    expect(startSpeedrunSolo).toHaveBeenCalledWith({ pool: "standard" });
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/training/s1"));
  });

  it("says when no fresh seed is left and disables Start", async () => {
    vi.mocked(fetchFreshSpeedrunSeeds).mockResolvedValue({ fresh: false });
    renderWindow();

    await screen.findByText("No fresh seed right now");
    const start = screen.getByRole("button", {
      name: "Start solo",
    }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
  });

  it("shows the server's refusal and stays open", async () => {
    vi.mocked(startSpeedrunSolo).mockRejectedValue(
      new Error("You already have an active solo session"),
    );
    renderWindow();

    const start = screen.getByRole("button", { name: "Start solo" });
    await waitFor(() =>
      expect((start as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(start);

    await screen.findByText("You already have an active solo session");
    expect(goto).not.toHaveBeenCalled();
  });
});

describe("Start a run: closed categories", () => {
  const CLOSED = "Random Seed runs are closed for this category.";

  function action(name: string): HTMLButtonElement {
    return screen.getByRole("button", { name }) as HTMLButtonElement;
  }

  it("closes a retired category's Random Seed without asking", async () => {
    auth.user = user("organizer");
    renderWindow({ retired: true });

    expect(screen.getByText(CLOSED)).toBeTruthy();
    expect(screen.queryByText("No fresh seed right now")).toBeNull();
    expect(action("Start solo").disabled).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: "Race" }));
    expect(action("Create race").disabled).toBe(true);
    expect(fetchFreshSpeedrunSeeds).not.toHaveBeenCalled();
  });

  it("closes an archive's Random Seed without asking", () => {
    renderWindow({ pool: "standard@25" });

    expect(screen.getByText(CLOSED)).toBeTruthy();
    expect(action("Start solo").disabled).toBe(true);
    expect(fetchFreshSpeedrunSeeds).not.toHaveBeenCalled();
  });

  it("closes it when the server cannot draw from the pool", async () => {
    vi.mocked(fetchFreshSpeedrunSeeds).mockResolvedValue(null);
    renderWindow();

    await screen.findByText(CLOSED);
    expect(screen.queryByText("No fresh seed right now")).toBeNull();
    expect(action("Start solo").disabled).toBe(true);
  });

  it("keeps Set Seed open on a retired category", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    renderWindow({ retired: true, initialSeed: SEED });

    await waitFor(() => expect(action("Start solo").disabled).toBe(false));
    expect(screen.queryByText(CLOSED)).toBeNull();
  });
});

describe("Start a run: a refusal belongs to its choice", () => {
  const REFUSAL = "You already have an active solo session";

  async function refuse() {
    const start = screen.getByRole("button", { name: "Start solo" });
    await waitFor(() =>
      expect((start as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(start);
    await screen.findByText(REFUSAL);
  }

  beforeEach(() => {
    vi.mocked(startSpeedrunSolo).mockRejectedValue(new Error(REFUSAL));
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
  });

  it("clears it when the seed mode changes", async () => {
    renderWindow();
    await refuse();

    await fireEvent.click(screen.getByRole("button", { name: "Set Seed" }));
    expect(screen.queryByText(REFUSAL)).toBeNull();
  });

  it("clears it when the format changes", async () => {
    auth.user = user("organizer");
    renderWindow();
    await refuse();

    await fireEvent.click(screen.getByRole("button", { name: "Race" }));
    expect(screen.queryByText(REFUSAL)).toBeNull();
  });

  it("clears it when the seed ID changes", async () => {
    renderWindow({ initialSeed: SEED });
    await refuse();

    await fireEvent.input(screen.getByLabelText("Seed ID"), {
      target: { value: "363096" },
    });
    expect(screen.queryByText(REFUSAL)).toBeNull();
  });
});

describe("Start a run: Set Seed", () => {
  async function typeSeed(value: string) {
    const input = screen.getByLabelText("Seed ID");
    await fireEvent.input(input, { target: { value } });
  }

  it("looks a seed up from 6 characters and shows its record", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    const { container } = renderWindow();
    await fireEvent.click(screen.getByRole("button", { name: "Set Seed" }));

    await typeSeed("36309");
    await sleep(400);
    expect(fetchSpeedrunSeedSummary).not.toHaveBeenCalled();

    await typeSeed("363096");
    await waitFor(() =>
      expect(fetchSpeedrunSeedSummary).toHaveBeenCalledWith("363096"),
    );
    await waitFor(() =>
      expect(text(container.querySelector(".seed-check"))).toBe(
        "✓ Replayable · WR 25:43 by Abisxoxo",
      ),
    );
    expect(fetchSpeedrunSeedSummary).toHaveBeenCalledTimes(1);
  });

  it("answers an unknown seed and keeps Start disabled", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockRejectedValue(
      new Error("Unknown seed"),
    );
    renderWindow({ initialSeed: "abcdef" });

    await screen.findByText("Unknown seed");
    expect(
      (screen.getByRole("button", { name: "Start solo" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("gives the reason a seed cannot be replayed and disables Start", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(
      summary({
        category_name: "Boss Rush",
        replayable: false,
        not_replayable_reason: "Its files were deleted.",
      }),
    );
    const { container } = renderWindow({ initialSeed: SEED });

    await screen.findByText(/Its files were deleted\./);
    expect(
      (screen.getByRole("button", { name: "Start solo" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(text(container.querySelector(".category-chip"))).toBe("Boss Rush");
  });

  it("starts a Set Seed solo run on the full seed number", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    vi.mocked(startSpeedrunSolo).mockResolvedValue({
      id: "s2",
    } as TrainingSessionDetail);
    renderWindow({ initialSeed: "363096" });

    const start = screen.getByRole("button", { name: "Start solo" });
    await waitFor(() =>
      expect((start as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(start);

    expect(startSpeedrunSolo).toHaveBeenCalledWith({ seed: SEED });
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/training/s2"));
  });

  it("fills in the board's record seed from the WR button", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    renderWindow({ initialSeed: "abc", recordSeed: SEED });

    await fireEvent.click(screen.getByRole("button", { name: "WR" }));

    expect((screen.getByLabelText("Seed ID") as HTMLInputElement).value).toBe(
      SEED,
    );
    await waitFor(() =>
      expect(fetchSpeedrunSeedSummary).toHaveBeenCalledWith(SEED),
    );
  });

  it("offers no WR button on a board without a record", async () => {
    renderWindow({ initialSeed: "" });

    expect(screen.queryByRole("button", { name: "WR" })).toBeNull();
  });

  it("keeps the answer to the latest keystroke", async () => {
    let answerFirst: (s: SpeedrunSeedSummary) => void = () => {};
    vi.mocked(fetchSpeedrunSeedSummary)
      .mockImplementationOnce(
        () => new Promise((resolve) => (answerFirst = resolve)),
      )
      .mockResolvedValueOnce(
        summary({ seed_number: "aaaaaa000001", category_name: "Sprint" }),
      );
    const { container } = renderWindow({ initialSeed: "aaaaaa" });
    await waitFor(() =>
      expect(fetchSpeedrunSeedSummary).toHaveBeenCalledTimes(1),
    );

    await typeSeed("aaaaaa0");
    await waitFor(() =>
      expect(text(container.querySelector(".category-chip"))).toBe("Sprint"),
    );
    answerFirst(summary({ category_name: "Boss Rush" }));
    await sleep(10);

    expect(text(container.querySelector(".category-chip"))).toBe("Sprint");
  });

  it("shows the seed's category, and the board's again without a seed", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(
      summary({ category: "boss_rush", category_name: "Boss Rush" }),
    );
    const { container } = renderWindow();
    const category = () => text(container.querySelector(".category-chip"));
    const board = () => text(container.querySelector(".explain .board"));
    expect(category()).toBe("Standard");

    await fireEvent.click(screen.getByRole("button", { name: "Set Seed" }));
    expect(board()).toBe("Standard · Set Seed");
    await typeSeed(SEED);
    await waitFor(() => expect(category()).toBe("Boss Rush"));
    expect(board()).toBe("Boss Rush · Set Seed");

    // Random Seed draws from the board's category.
    await fireEvent.click(screen.getByRole("button", { name: "Random Seed" }));
    expect(category()).toBe("Standard");
    await fireEvent.click(screen.getByRole("button", { name: "Set Seed" }));
    expect(category()).toBe("Boss Rush");

    await typeSeed("");
    expect(category()).toBe("Standard");
    expect(board()).toBe("Standard · Set Seed");
  });
});

describe("Start a run: format", () => {
  it("offers Race to organizers and admins only", async () => {
    const first = renderWindow();
    expect(screen.queryByRole("button", { name: "Race" })).toBeNull();
    first.unmount();

    auth.user = user("organizer");
    renderWindow();
    expect(screen.getByRole("button", { name: "Race" })).toBeTruthy();
  });

  it("creates a speedrun race on the board's pool", async () => {
    auth.user = user("admin");
    renderWindow();
    await fireEvent.click(screen.getByRole("button", { name: "Race" }));

    const create = screen.getByRole("button", { name: "Create race" });
    await waitFor(() =>
      expect((create as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(create);

    expect(goto).toHaveBeenCalledWith("/race/new?mode=speedrun&pool=standard");
    expect(startSpeedrunSolo).not.toHaveBeenCalled();
  });

  it("creates a Set Seed race on the seed found", async () => {
    auth.user = user("organizer");
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    renderWindow({ initialSeed: "363096" });
    await fireEvent.click(screen.getByRole("button", { name: "Race" }));

    const create = screen.getByRole("button", { name: "Create race" });
    await waitFor(() =>
      expect((create as HTMLButtonElement).disabled).toBe(false),
    );
    await fireEvent.click(create);

    expect(goto).toHaveBeenCalledWith(`/race/new?seed=${SEED}`);
  });
});

describe("Start a run: logged out", () => {
  it("asks to log in instead of starting", () => {
    auth.user = null;
    renderWindow();

    expect(
      screen.getByRole("link", { name: "Login with Twitch" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start solo" })).toBeNull();
  });
});
