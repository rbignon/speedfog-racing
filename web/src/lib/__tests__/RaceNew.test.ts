import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { flushSync } from "svelte";

import { pageState } from "./pageState.svelte";

vi.mock("$app/state", async () => {
  const { pageState } = await import("./pageState.svelte");
  return { page: pageState };
});
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchPoolStats: vi.fn(),
    fetchSpeedrunSeedSummary: vi.fn(),
  };
});

import { goto } from "$app/navigation";
import RaceNewPage from "../../routes/race/new/+page.svelte";
import {
  fetchPoolStats,
  fetchSpeedrunSeedSummary,
  type AuthUser,
  type PoolConfig,
  type PoolInfo,
  type SpeedrunSeedSummary,
} from "$lib/api";
import { auth } from "$lib/stores/auth.svelte";

const SEED = "363096a4243f";

const ORGANIZER: AuthUser = {
  id: "u1",
  twitch_username: "org",
  twitch_display_name: "Org",
  twitch_avatar_url: null,
  role: "organizer",
  locale: null,
  overlay_settings: null,
  feedback_prompted_at: null,
  race_count: 0,
  daily_count: 0,
  training_count: 0,
};

function pool(
  name: string,
  sortOrder: number,
  available: number,
  seen = 0,
  speedrunFloor = 0,
): PoolInfo {
  return {
    available,
    seen,
    speedrun_floor: speedrunFloor,
    consumed: 0,
    discarded: 0,
    played_by_user: null,
    pool_config: { name, sort_order: sortOrder } as PoolConfig,
  };
}

function summary(over: Partial<SpeedrunSeedSummary> = {}): SpeedrunSeedSummary {
  return {
    seed_number: SEED,
    category: "standard",
    category_name: "Standard",
    replayable: true,
    not_replayable_reason: null,
    record: null,
    ...over,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

function postedBody(): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url).endsWith("/races") &&
      (init as RequestInit | undefined)?.method === "POST",
  );
  if (!call) throw new Error("no POST /races");
  return JSON.parse(String((call[1] as RequestInit).body));
}

async function openPage(search: string) {
  pageState.url = new URL(`http://localhost/race/new${search}`);
  const view = render(RaceNewPage);
  await screen.findByRole("button", { name: "Create Race" });
  return view;
}

// The Speedrun race option sits in the Advanced options panel, folded by
// default: unfold it first.
async function speedrunOption(): Promise<HTMLInputElement | null> {
  if (!screen.queryByText("Late joiners")) {
    await fireEvent.click(
      screen.getByRole("button", { name: /Advanced options/ }),
    );
  }
  return screen.queryByLabelText("Speedrun race") as HTMLInputElement | null;
}

async function submitPrivate(name: string) {
  await fireEvent.input(screen.getByLabelText("Race Name"), {
    target: { value: name },
  });
  await fireEvent.click(screen.getByLabelText("Private"));
  await fireEvent.click(screen.getByRole("button", { name: "Create Race" }));
}

beforeEach(() => {
  auth.user = ORGANIZER;
  auth.initialized = true;
  vi.mocked(goto).mockReset();
  vi.mocked(fetchPoolStats).mockResolvedValue({
    standard: pool("Standard", 1, 6),
    sprint: pool("Sprint", 2, 4),
  });
  vi.mocked(fetchSpeedrunSeedSummary).mockReset();
  fetchMock = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ id: "r9" }), { status: 201 }),
    );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  auth.user = null;
  auth.initialized = false;
});

describe("/race/new: the Speedrun race option", () => {
  it("is on with the pool picked from ?mode=speedrun&pool=", async () => {
    const { container } = await openPage("?mode=speedrun&pool=sprint");

    // Folded, the Advanced options trigger already shows it on.
    const active = [...container.querySelectorAll(".advanced-option.active")];
    expect(active.map((el) => el.textContent?.trim())).toContain("✓ speedrun");
    expect((await speedrunOption())?.checked).toBe(true);
    expect(
      screen.getByRole("tab", { name: /Sprint/ }).getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("names the selected pool in the race name suggestion", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      standard: pool("Standard", 1, 6),
      uwyg_rush: pool("UWYG Boss Rush", 2, 4),
    });
    await openPage("?mode=speedrun&pool=uwyg_rush");
    const nameInput = screen.getByLabelText("Race Name") as HTMLInputElement;
    expect(nameInput.placeholder).toBe("e.g. UWYG Boss Rush Grinding");

    await fireEvent.click(screen.getByRole("tab", { name: /Standard/ }));
    expect(nameInput.placeholder).toBe("e.g. Standard Grinding");

    await fireEvent.click((await speedrunOption())!);
    expect(nameInput.placeholder).toBe("e.g. Sunday Showdown");
  });

  it("stays off when ?pool= alone picks the pool", async () => {
    await openPage("?pool=sprint");

    expect((await speedrunOption())?.checked).toBe(false);
    expect(
      screen.getByRole("tab", { name: /Sprint/ }).getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("sends the race's mode", async () => {
    await openPage("?mode=speedrun&pool=sprint");
    await submitPrivate("Fast one");

    await waitFor(() => expect(goto).toHaveBeenCalledWith("/race/r9"));
    expect(postedBody()).toMatchObject({
      pool_name: "sprint",
      mode: "speedrun",
      seed: null,
    });
  });

  it("sends a normal race when the option is left off", async () => {
    await openPage("");
    await submitPrivate("Plain one");

    await waitFor(() => expect(goto).toHaveBeenCalledWith("/race/r9"));
    expect(postedBody()).toMatchObject({ mode: "normal", seed: null });
  });
});

describe("/race/new: seen seeds", () => {
  it("lets a normal race, not a speedrun race, draw from a pool with only seen seeds", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      standard: pool("Standard", 1, 0),
      sprint: pool("Sprint", 2, 0, 2),
    });
    await openPage("");

    const sprint = screen.getByRole("tab", {
      name: /Sprint/,
    }) as HTMLButtonElement;
    const create = screen.getByRole("button", {
      name: "Create Race",
    }) as HTMLButtonElement;
    expect(sprint.disabled).toBe(false);
    expect(sprint.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText(/2 seeds available/)).toBeTruthy();
    expect(create.disabled).toBe(false);

    await fireEvent.click((await speedrunOption())!);

    expect(sprint.disabled).toBe(true);
    expect(create.disabled).toBe(true);
    expect(
      screen.getByText("No fresh seed right now in any game mode."),
    ).toBeTruthy();
  });

  it("warns a normal race that a pool at its floor would give it a seen seed", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      // Above its floor: a fresh seed.
      standard: pool("Standard", 1, 6, 3, 5),
      // At its floor with seen seeds: one of them.
      sprint: pool("Sprint", 2, 4, 2, 4),
      // At its floor without any: the reserve, fresh.
      long: pool("Long", 3, 3, 0, 5),
    });
    await openPage("?pool=sprint");
    const warning = /Low on fresh seeds right now/;

    expect(screen.getByText(warning)).toBeTruthy();

    await fireEvent.click(screen.getByRole("tab", { name: /Standard/ }));
    expect(screen.queryByText(warning)).toBeNull();
    await fireEvent.click(screen.getByRole("tab", { name: /Long/ }));
    expect(screen.queryByText(warning)).toBeNull();

    // A speedrun race never draws a seen seed.
    await fireEvent.click(screen.getByRole("tab", { name: /Sprint/ }));
    await fireEvent.click((await speedrunOption())!);
    expect(screen.queryByText(warning)).toBeNull();
  });

  it("disables Create when the speedrun option leaves the selected pool with nothing to draw", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      standard: pool("Standard", 1, 3),
      sprint: pool("Sprint", 2, 0, 2),
    });
    await openPage("?pool=sprint");

    const create = screen.getByRole("button", {
      name: "Create Race",
    }) as HTMLButtonElement;
    expect(create.disabled).toBe(false);

    await fireEvent.click((await speedrunOption())!);

    // Another pool still has seeds, but the selected one has none to draw.
    expect(create.disabled).toBe(true);
  });
});

describe("/race/new: the speedrun floor", () => {
  it("keeps a speedrun race off a pool at its floor and counts only the seeds above it", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      standard: pool("Standard", 1, 6, 0, 5),
      sprint: pool("Sprint", 2, 4, 0, 4),
      long: pool("Long", 3, 3, 0, 5),
    });
    await openPage("?pool=sprint");

    const sprint = screen.getByRole("tab", {
      name: /Sprint/,
    }) as HTMLButtonElement;
    const create = screen.getByRole("button", {
      name: "Create Race",
    }) as HTMLButtonElement;
    expect(screen.getByText(/4 seeds available/)).toBeTruthy();
    expect(create.disabled).toBe(false);

    await fireEvent.click((await speedrunOption())!);

    // The server would refuse the draw: the floor's seeds are a reserve.
    expect(sprint.disabled).toBe(true);
    expect(
      (screen.getByRole("tab", { name: /Long/ }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(create.disabled).toBe(true);
    expect(screen.getByText("No fresh seed right now")).toBeTruthy();

    await fireEvent.click(screen.getByRole("tab", { name: /Standard/ }));

    expect(create.disabled).toBe(false);
    expect(screen.getByText(/1 seed available/)).toBeTruthy();
  });

  it("picks a pool above its floor when ?mode=speedrun asks for one at it", async () => {
    vi.mocked(fetchPoolStats).mockResolvedValue({
      standard: pool("Standard", 1, 6, 0, 5),
      sprint: pool("Sprint", 2, 4, 0, 4),
    });
    await openPage("?mode=speedrun&pool=sprint");

    expect(
      screen
        .getByRole("tab", { name: /Standard/ })
        .getAttribute("aria-selected"),
    ).toBe("true");
    expect(
      (screen.getByRole("button", { name: "Create Race" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });
});

describe("/race/new?seed=: a Set Seed race", () => {
  it("shows the banner and the seed in place of the mode grid", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    const { container } = await openPage("?seed=363096");

    await screen.findByText("Change seed");
    expect(fetchSpeedrunSeedSummary).toHaveBeenCalledWith("363096");
    expect(screen.getByRole("heading", { level: 1 }).textContent?.trim()).toBe(
      "Create Set Seed Race",
    );
    // The heading's tag names the seed in full, not the URL's short form.
    expect(
      screen.getByRole("link", { name: `Seed ${SEED}` }).getAttribute("href"),
    ).toBe(`/speedrun/seed/${SEED}`);
    const banner = container.querySelector(".set-seed-banner");
    expect(banner?.textContent).toContain(
      "Runners may already know this seed.",
    );
    expect(screen.getByText("Change seed").getAttribute("href")).toBe(
      `/speedrun?pool=standard&start=set&seed=${SEED}`,
    );
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(await speedrunOption()).toBeNull();
    expect(screen.getByText(`Seed ${SEED}, fixed: no reroll`)).toBeTruthy();
  });

  it("names the seed's pool, not the first listed one, in the race name suggestion", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(
      summary({ category: "sprint", category_name: "Sprint" }),
    );
    await openPage(`?seed=${SEED}`);
    await screen.findByText("Change seed");

    expect(
      (screen.getByLabelText("Race Name") as HTMLInputElement).placeholder,
    ).toBe("e.g. Sprint Grinding");
  });

  it("creates the race on the seed, in Set Seed mode", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    await openPage("?seed=363096");
    await screen.findByText("Change seed");

    await submitPrivate("Grinding");

    await waitFor(() => expect(goto).toHaveBeenCalledWith("/race/r9"));
    expect(postedBody()).toMatchObject({ mode: "set_seed", seed: SEED });
  });

  it("gives the reason and disables Create for a seed that cannot be replayed", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(
      summary({
        replayable: false,
        not_replayable_reason: "Its files were deleted.",
      }),
    );
    await openPage(`?seed=${SEED}`);

    await screen.findByText("Its files were deleted.");
    expect(
      (screen.getByRole("button", { name: "Create Race" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("says when the seed is unknown and disables Create", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockRejectedValue(
      new Error("Unknown seed"),
    );
    await openPage("?seed=zzzzzz");

    await screen.findByText("Unknown seed");
    // The heading's tag keeps the URL's ID, with no seed page to link to.
    expect(screen.getByText("Seed zzzzzz")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /^Seed / })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Create Race" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("turns back into a plain form when a link drops the seed", async () => {
    vi.mocked(fetchSpeedrunSeedSummary).mockResolvedValue(summary());
    await openPage("?seed=363096");
    await screen.findByText("Change seed");

    // The navbar's Create Race reuses the mounted page.
    pageState.url = new URL("http://localhost/race/new");
    flushSync();

    await waitFor(() => expect(screen.queryByText("Change seed")).toBeNull());
    expect(screen.getByRole("heading", { level: 1 }).textContent?.trim()).toBe(
      "Create Race",
    );
    expect(screen.queryByText(/^Seed /)).toBeNull();
    expect(screen.getByRole("tablist")).toBeTruthy();
    expect((await speedrunOption())?.checked).toBe(false);
  });
});
