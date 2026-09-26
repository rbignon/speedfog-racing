import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import CastSetup from "$lib/components/cast/CastSetup.svelte";
import type { RaceDetail } from "$lib/api";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchEvents: vi.fn().mockResolvedValue([]),
    fetchEvent: vi.fn().mockResolvedValue({ stages: [], showcases: [] }),
  };
});

function fakeParticipant(id: string, username: string, colorIndex: number) {
  return {
    id,
    user: {
      id: `u-${id}`,
      twitch_username: username,
      twitch_display_name: null,
      twitch_avatar_url: null,
    },
    status: "playing",
    current_layer: 0,
    igt_ms: 0,
    death_count: 0,
    color_index: colorIndex,
  };
}

function fakeRace(id = "race-1"): RaceDetail {
  return {
    id,
    participants: [
      fakeParticipant("p1", "alice", 0),
      fakeParticipant("p2", "bob", 1),
      fakeParticipant("p3", "carol", 2),
      fakeParticipant("p4", "dave", 3),
    ],
    casters: [],
  } as unknown as RaceDetail;
}

beforeEach(() => {
  try {
    localStorage.clear();
  } catch {
    // Not every environment allows it; the tests just start from defaults.
  }
});

describe("CastSetup: hole assignment", () => {
  it("seats the field in join order by default", () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace(), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");
    expect(selects).toHaveLength(4);
    expect([...selects].map((s) => s.value)).toEqual([
      "alice",
      "bob",
      "carol",
      "dave",
    ]);
  });

  it("refuses to seat a runner already seated in another hole", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-2"), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    // POV 1 already holds alice; naming her again in POV 2 is refused
    // rather than silently leaving bob unshown.
    await fireEvent.change(selects[1], { target: { value: "alice" } });

    expect(selects[1].value).toBe("bob");
    expect(container.textContent).toContain("Already seated in POV 1.");
  });

  it("accepts the same runner once their old hole is freed first", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-3"), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    await fireEvent.change(selects[0], { target: { value: "" } });
    await fireEvent.change(selects[1], { target: { value: "alice" } });

    expect(selects[1].value).toBe("alice");
    expect(container.textContent).not.toContain("Already seated");
  });
});

function selectScenePill(container: HTMLElement, label: string) {
  const btn = [...container.querySelectorAll(".scene-picker .pill")].find(
    (b) => b.textContent?.trim() === label,
  ) as HTMLButtonElement | undefined;
  if (!btn) throw new Error(`no scene pill labelled ${label}`);
  return fireEvent.click(btn);
}

describe("CastSetup: OBS positions", () => {
  it("never lists the metro map as a position to place a video source at", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-4"), onClose: () => {} },
    });
    await selectScenePill(container, "Metro");

    const text = container.querySelector(".positions")?.textContent ?? "";
    expect(text).not.toContain("METRO MAP");
    // The desk's cam holes are still real OBS sources, so they stay listed.
    expect(text).toContain("CAM 1");
  });
});

describe("CastSetup: talk scene URL guard", () => {
  it("withholds the copyable URL and the preview until an event and stage are chosen", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-5"), onClose: () => {} },
    });
    await selectScenePill(container, "Talk");

    expect(container.querySelector("iframe.preview")).toBeNull();
    expect(container.querySelector(".preview-empty")).not.toBeNull();
    expect(container.querySelector(".url-input")).toBeNull();
    expect(container.textContent).toContain(
      "Pick an event and stage above to get this scene's URL.",
    );
  });
});
