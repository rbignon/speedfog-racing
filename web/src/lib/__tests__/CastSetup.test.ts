import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/svelte";
import CastSetup from "$lib/components/cast/CastSetup.svelte";
import {
  fetchEvent,
  fetchEvents,
  type EventDetail,
  type EventSummary,
  type RaceDetail,
} from "$lib/api";
import { copyToClipboard } from "$lib/utils/clipboard";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchEvents: vi.fn(),
    fetchEvent: vi.fn(),
  };
});

vi.mock("$lib/utils/clipboard", () => ({
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));

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

function fakeRace(
  id = "race-1",
  event: { event_slug: string; event_slot: string } | null = null,
): RaceDetail {
  return {
    id,
    event_slug: event?.event_slug ?? null,
    event_slot: event?.event_slot ?? null,
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
  vi.mocked(copyToClipboard).mockClear();
  // No event on the bill unless a test serves one (see serveSeasonOne).
  vi.mocked(fetchEvents).mockResolvedValue([]);
  vi.mocked(fetchEvent).mockResolvedValue({
    stages: [],
    showcases: [],
  } as unknown as EventDetail);
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

  it("offers no hole assignment on a scene that seats nobody", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-12"), onClose: () => {} },
    });
    for (const label of ["Metro", "Browser", "Talk"]) {
      await selectScenePill(container, label);
      expect(container.querySelectorAll(".hole-grid select")).toHaveLength(0);
    }
  });

  it("keeps the seats picked on a scene that seats nobody for the next one", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-13"), onClose: () => {} },
    });
    const seats = () =>
      [
        ...container.querySelectorAll<HTMLSelectElement>(".hole-grid select"),
      ].map((s) => s.value);
    const pov1 =
      container.querySelector<HTMLSelectElement>(".hole-grid select")!;
    await fireEvent.change(pov1, { target: { value: "" } });
    await selectScenePill(container, "Metro");
    await selectScenePill(container, "Quad");

    // POV 1 freed by hand, the others still the defaults: a reset would
    // bring alice back, a wipe would leave every hole on auto.
    expect(seats()).toEqual(["", "bob", "carol", "dave"]);
    expect(urlInputValue(container)).not.toContain("p1=");
    expect(urlInputValue(container)).toContain("p2=bob");
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

function scenePillLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".scene-picker .pill")].map(
    (b) => b.textContent?.trim() ?? "",
  );
}

function urlInputValue(container: HTMLElement): string {
  return (container.querySelector(".url-input") as HTMLInputElement).value;
}

describe("CastSetup: scene list", () => {
  it("offers the browser scene and builds its URL", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-9"), onClose: () => {} },
    });
    await selectScenePill(container, "Browser");

    expect(urlInputValue(container)).toContain(
      "/overlay/cast/race/race-9/browser?",
    );
    const text = container.querySelector(".positions")?.textContent ?? "";
    expect(text).toContain("BROWSER");
  });

  it("copies every race scene the picker offers with Copy all", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-10"), onClose: () => {} },
    });
    // Talk needs an event and a stage first, so it stays out of Copy all
    // until then (see the talk scene URL guard below).
    const offered = new Set<string>();
    for (const label of scenePillLabels(container)) {
      if (label === "Talk") continue;
      await selectScenePill(container, label);
      offered.add(new URL(urlInputValue(container)).pathname);
    }

    const copyAll = [...container.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === "Copy all scene URLs",
    ) as HTMLButtonElement;
    await fireEvent.click(copyAll);

    expect(copyToClipboard).toHaveBeenCalledTimes(1);
    const copied = vi.mocked(copyToClipboard).mock.calls[0][0];
    expect(new Set(copied.split("\n").map((u) => new URL(u).pathname))).toEqual(
      offered,
    );
  });

  it("reopens on whichever scene the caster last picked", async () => {
    const race = fakeRace("race-11");
    const first = render(CastSetup, { props: { race, onClose: () => {} } });
    const labels = scenePillLabels(first.container);
    first.unmount();

    for (const label of labels) {
      const before = render(CastSetup, { props: { race, onClose: () => {} } });
      await selectScenePill(before.container, label);
      before.unmount();

      const after = render(CastSetup, { props: { race, onClose: () => {} } });
      expect(
        after.container
          .querySelector(".scene-picker .pill.active")
          ?.textContent?.trim(),
      ).toBe(label);
      after.unmount();
    }
  });
});

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

describe("CastSetup: duel scene", () => {
  it("frees a hidden slot's runner for a duel hole instead of refusing", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-7"), onClose: () => {} },
    });
    await selectScenePill(container, "Duel");
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    // carol sits in slot 3 by default, a hole the duel scene doesn't render
    // (and so can't be freed from): seating her in POV 1 must clear that
    // hidden slot, not refuse with an error about an invisible dropdown.
    await fireEvent.change(selects[0], { target: { value: "carol" } });

    expect(selects[0].value).toBe("carol");
    expect(container.textContent).not.toContain("Already seated");
  });

  it("still refuses a duplicate between the duel scene's own two holes", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-8"), onClose: () => {} },
    });
    await selectScenePill(container, "Duel");
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    await fireEvent.change(selects[1], { target: { value: "alice" } });

    expect(selects[1].value).toBe("bob");
    expect(container.textContent).toContain("Already seated in POV 1.");
  });

  it("offers only the duel scene's two holes and builds its URL", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-6"), onClose: () => {} },
    });
    await selectScenePill(container, "Duel");

    const labels = [
      ...container.querySelectorAll(".hole-grid .field > span:first-child"),
    ].map((e) => e.textContent);
    expect(labels).toEqual(["POV 1", "POV 2"]);
    const url = (container.querySelector(".url-input") as HTMLInputElement)
      .value;
    expect(url).toContain("/overlay/cast/race/race-6/duel");
    expect(url).not.toContain("p3=");
  });
});

// The two calls the panel makes for its co-brand and stage pickers, answered
// for one event, Season One, with a stage and a showcase.
function serveSeasonOne({ onTheBill }: { onTheBill: boolean }) {
  vi.mocked(fetchEvents).mockResolvedValue(
    (onTheBill
      ? [{ slug: "season-one", name: "Season One" }]
      : []) as unknown as EventSummary[],
  );
  vi.mocked(fetchEvent).mockResolvedValue({
    slug: "season-one",
    name: "Season One",
    stages: [{ key: "semi_b", label: "Semi B" }],
    showcases: [{ key: "ignite_showcase", label: "Ignite showcase" }],
  } as unknown as EventDetail);
}

describe("CastSetup: prefill from the race's event", () => {
  it.each([
    ["a stage", "semi_b:2", "semi_b", "Semi B"],
    ["a showcase", "ignite_showcase:1", "ignite_showcase", "Ignite showcase"],
  ])(
    "co-brands with the race's event and picks its stage on %s race",
    async (_, slot, stage, label) => {
      serveSeasonOne({ onTheBill: true });
      const race = fakeRace(`race-${stage}`, {
        event_slug: "season-one",
        event_slot: slot,
      });
      const { container } = render(CastSetup, {
        props: { race, onClose: () => {} },
      });

      expect(urlInputValue(container)).toContain("event=season-one");
      await selectScenePill(container, "Talk");
      expect(urlInputValue(container)).toContain(
        `/overlay/cast/event/season-one/${stage}/talk`,
      );
      const stagePicker = [
        ...container.querySelectorAll<HTMLSelectElement>("select"),
      ].find((s) =>
        [...s.options].some((o) => o.textContent === "Select a stage"),
      )!;
      await waitFor(() =>
        expect(stagePicker.selectedOptions[0]?.textContent).toBe(label),
      );
    },
  );

  it("co-brands a qualifier race but leaves the talk scene's stage to pick", async () => {
    serveSeasonOne({ onTheBill: true });
    const race = fakeRace("race-q", {
      event_slug: "season-one",
      event_slot: "qualifier:standard:1",
    });
    const { container } = render(CastSetup, {
      props: { race, onClose: () => {} },
    });

    expect(urlInputValue(container)).toContain("event=season-one");
    await selectScenePill(container, "Talk");
    expect(container.querySelector(".url-input")).toBeNull();
  });

  it("keeps a setup already saved for the race, a cleared co-brand included", async () => {
    serveSeasonOne({ onTheBill: true });
    const race = fakeRace("race-saved", {
      event_slug: "season-one",
      event_slot: "semi_b:1",
    });
    localStorage.setItem(
      "cast-setup:race-saved",
      JSON.stringify({ scene: "quad", eventSlug: "", stageKey: "" }),
    );
    const { container } = render(CastSetup, {
      props: { race, onClose: () => {} },
    });

    expect(urlInputValue(container)).not.toContain("event=");
  });

  it("names the race's own event in the co-brand picker once it is off the bill", async () => {
    serveSeasonOne({ onTheBill: false });
    const race = fakeRace("race-past", {
      event_slug: "season-one",
      event_slot: "final:1",
    });
    const { container } = render(CastSetup, {
      props: { race, onClose: () => {} },
    });

    const coBrand = () =>
      [...container.querySelectorAll<HTMLSelectElement>("select")].find((s) =>
        [...s.options].some((o) => o.textContent === "None"),
      )!;
    await waitFor(() =>
      expect(coBrand().selectedOptions[0]?.textContent).toBe("Season One"),
    );
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
