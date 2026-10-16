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
import { downloadJson } from "$lib/cast/obs-export";

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

// The real seats and file names; only the browser download is captured.
vi.mock("$lib/cast/obs-export", async () => {
  const actual = await vi.importActual<typeof import("$lib/cast/obs-export")>(
    "$lib/cast/obs-export",
  );
  return { ...actual, downloadJson: vi.fn() };
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

function fakeRace(
  id = "race-1",
  event: { event_slug: string; event_slot: string } | null = null,
): RaceDetail {
  return {
    id,
    name: `Race ${id}`,
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
  vi.mocked(downloadJson).mockClear();
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
  it("leaves every hole to the scene's join-order fallback by default", () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace(), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");
    expect(selects).toHaveLength(4);
    expect([...selects].map((s) => s.value)).toEqual(["", "", "", ""]);
    // No p<n> at all: the scene seats the live field, not the field as it
    // stood when the panel was first opened.
    expect(urlInputValue(container)).not.toMatch(/[?&]p\d=/);
  });

  it("refuses to seat a runner already seated in another hole", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-2"), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");
    await fireEvent.change(selects[0], { target: { value: "alice" } });
    await fireEvent.change(selects[1], { target: { value: "bob" } });

    // POV 1 holds alice; naming her again in POV 2 is refused rather than
    // silently leaving bob unshown, and POV 2 keeps bob.
    await fireEvent.change(selects[1], { target: { value: "alice" } });

    expect(selects[1].value).toBe("bob");
    expect(urlInputValue(container)).toContain("p2=bob");
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
    const pov2 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[1];
    await fireEvent.change(pov2, { target: { value: "bob" } });
    await selectScenePill(container, "Metro");
    await selectScenePill(container, "Quad");

    // POV 2 picked by hand, the others still on auto: a reset would wipe
    // bob, a reshuffle would move him.
    expect(seats()).toEqual(["", "bob", "", ""]);
    expect(urlInputValue(container)).not.toContain("p1=");
    expect(urlInputValue(container)).toContain("p2=bob");
  });

  it("names who each auto hole seats, shifted by a pick", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-14"), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    await fireEvent.change(selects[0], { target: { value: "dave" } });

    // dave leaves the join-order pool: the silent holes seat the rest in
    // order, and POV 1's own auto option says who clearing it would seat.
    expect(autoOptionLabels(container)).toEqual([
      "(auto: alice)",
      "(auto: alice)",
      "(auto: bob)",
      "(auto: carol)",
    ]);
  });

  it("names nobody in an auto hole past the field", () => {
    const race = fakeRace("race-15");
    race.participants = race.participants.slice(0, 3);
    const { container } = render(CastSetup, {
      props: { race, onClose: () => {} },
    });

    expect(autoOptionLabels(container)[3]).toBe("(auto: nobody)");
  });

  it("accepts the same runner once their old hole is freed first", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-3"), onClose: () => {} },
    });
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    await fireEvent.change(selects[0], { target: { value: "alice" } });
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

function autoOptionLabels(container: HTMLElement): string[] {
  return [
    ...container.querySelectorAll<HTMLSelectElement>(".hole-grid select"),
  ].map((s) => s.options[0].textContent?.trim() ?? "");
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
    const pov3 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[2];
    await fireEvent.change(pov3, { target: { value: "carol" } });
    await selectScenePill(container, "Duel");
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    // carol was seated in slot 3 on quad, a hole the duel scene doesn't
    // render (and so can't be freed from): seating her in POV 1 must clear
    // that hidden slot, not refuse with an error about an invisible dropdown.
    await fireEvent.change(selects[0], { target: { value: "carol" } });

    expect(selects[0].value).toBe("carol");
    expect(container.textContent).not.toContain("Already seated");

    // Back on quad, she sits in POV 1 only.
    await selectScenePill(container, "Quad");
    const quadSeats = [
      ...container.querySelectorAll<HTMLSelectElement>(".hole-grid select"),
    ].map((s) => s.value);
    expect(quadSeats).toEqual(["carol", "", "", ""]);
  });

  it("still refuses a duplicate between the duel scene's own two holes", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-8"), onClose: () => {} },
    });
    await selectScenePill(container, "Duel");
    const selects =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select");

    await fireEvent.change(selects[0], { target: { value: "alice" } });
    await fireEvent.change(selects[1], { target: { value: "alice" } });

    expect(selects[1].value).toBe("");
    expect(container.textContent).toContain("Already seated in POV 1.");
  });

  it("offers only the duel scene's two holes and builds its URL", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-6"), onClose: () => {} },
    });
    const pov3 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[2];
    await fireEvent.change(pov3, { target: { value: "carol" } });
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

  it("leaves a hidden slot's pick out of the duel's auto holes", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-16"), onClose: () => {} },
    });
    const pov3 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[2];
    await fireEvent.change(pov3, { target: { value: "alice" } });
    await selectScenePill(container, "Duel");

    // The duel scene reads p1 and p2 only, so alice, picked for quad's
    // POV 3, is still the first runner its silent holes seat.
    expect(autoOptionLabels(container)).toEqual([
      "(auto: alice)",
      "(auto: bob)",
    ]);
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
    stages: [{ key: "semi_b", label: "Semi B", field: [] }],
    showcases: [
      { key: "ignite_showcase", label: "Ignite showcase", field: [] },
    ],
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

type Obj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// The race's own event as the OBS files read it: Season One, whose Group G
// seats `field` (null: a seat whose runner is not known yet; `forfeited`
// names who withdrew after the lock), plus a showcase, which declares no
// field.
function serveGroupG(
  field: (string | null)[],
  { forfeited = [] }: { forfeited?: string[] } = {},
) {
  vi.mocked(fetchEvent).mockResolvedValue({
    slug: "season-one",
    name: "Season One",
    stages: [
      {
        key: "group_g",
        label: "Group G",
        field: field.map((username) => ({
          user: username
            ? {
                id: `u-${username}`,
                twitch_username: username,
                twitch_display_name: null,
                twitch_avatar_url: null,
              }
            : null,
          label: "1st of Group A",
          forfeited: username !== null && forfeited.includes(username),
          source: null,
          place: null,
        })),
      },
    ],
    showcases: [
      { key: "ignite_showcase", label: "Ignite showcase", field: [] },
    ],
  } as unknown as EventDetail);
}

const RACE_FILE = "Download OBS scenes";
const MATCH_FILE = "Download OBS scenes for the match";
const UNSETTLED =
  "The match's field is not settled yet: seats without a runner stay empty.";

function buttonLabelled(container: HTMLElement, label: string) {
  return [...container.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === label,
  );
}

function casterInputs(container: HTMLElement) {
  return container.querySelectorAll<HTMLInputElement>(
    'input[placeholder="twitch username"]',
  );
}

function inGroupG(id: string, n: number) {
  return fakeRace(id, { event_slug: "season-one", event_slot: `group_g:${n}` });
}

/** The panel's text with its markup's line wraps collapsed. */
function textOf(container: HTMLElement): string {
  return (container.textContent ?? "").replace(/\s+/g, " ");
}

/** Lets every pending request answer and the panel render what it got. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** The plate URL of the scene a downloaded collection names `scene`. */
function plateUrl(collection: Obj, scene: string): string {
  const items: Obj[] = collection.sources.find((s: Obj) => s.name === scene)
    .settings.items;
  const top = items[items.length - 1];
  return collection.sources.find((s: Obj) => s.uuid === top.source_uuid)
    .settings.url;
}

describe("CastSetup: OBS scene files", () => {
  it("offers the match file only on a stage or showcase slot", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    for (const race of [
      fakeRace("race-o1", {
        event_slug: "season-one",
        event_slot: "qualifier:standard:1",
      }),
      fakeRace("race-o2"),
    ]) {
      const { container, unmount } = render(CastSetup, {
        props: { race, onClose: () => {} },
      });
      await settle();
      expect(buttonLabelled(container, RACE_FILE)).toBeDefined();
      expect(buttonLabelled(container, MATCH_FILE)).toBeUndefined();
      unmount();
    }

    for (const slot of ["group_g:2", "ignite_showcase:1"]) {
      const { container, unmount } = render(CastSetup, {
        props: {
          race: fakeRace(`race-${slot}`, {
            event_slug: "season-one",
            event_slot: slot,
          }),
          onClose: () => {},
        },
      });
      await waitFor(() =>
        expect(buttonLabelled(container, MATCH_FILE)).toBeDefined(),
      );
      unmount();
    }
  });

  it("the match file is the same from any race of the stage", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    localStorage.setItem(
      "cast-setup:stage:season-one:group_g",
      JSON.stringify({
        scene: "quad",
        focusSlot: 1,
        slots: [null, "carol", null, null],
        cams: 1,
        caster1: "ann",
        caster2: "",
        delayS: 4,
        eventSlug: "season-one",
        stageKey: "group_g",
      }),
    );
    // Race 2 joined in another order, has its own caster, and kept a setup
    // of its own from before the stage's.
    const races = [inGroupG("race-g1", 1), inGroupG("race-g2", 2)];
    races[1].participants = [...races[1].participants]
      .reverse()
      .map((p, i) => ({ ...p, color_index: i }));
    races[1].casters = [
      { user: { twitch_username: "otto" } },
    ] as unknown as RaceDetail["casters"];
    localStorage.setItem("cast-setup:race-g2", JSON.stringify({ delayS: 9 }));

    for (const [i, race] of races.entries()) {
      const { container, unmount } = render(CastSetup, {
        props: { race, onClose: () => {} },
      });
      await waitFor(() =>
        expect(buttonLabelled(container, MATCH_FILE)).toBeDefined(),
      );
      await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
      await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(i + 1));
      unmount();
    }

    const calls = vi.mocked(downloadJson).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[1]).toEqual(calls[0]);
    // Keyed by the stage, it names neither race.
    expect(JSON.stringify(calls[0])).not.toMatch(/race-g\d/);
  });

  it("settings are shared across a stage's races", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    const first = render(CastSetup, {
      props: { race: inGroupG("race-s1", 1), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(first.container, MATCH_FILE)).toBeDefined(),
    );
    await fireEvent.input(casterInputs(first.container)[0], {
      target: { value: "ann" },
    });
    first.unmount();

    const second = render(CastSetup, {
      props: { race: inGroupG("race-s2", 2), onClose: () => {} },
    });
    await waitFor(() =>
      expect(casterInputs(second.container)[0].value).toBe("ann"),
    );
  });

  it("a showcase keeps its settings per race", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    const showcaseRace = (id: string, n: number) =>
      fakeRace(id, {
        event_slug: "season-one",
        event_slot: `ignite_showcase:${n}`,
      });
    const first = render(CastSetup, {
      props: { race: showcaseRace("race-c1", 1), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(first.container, MATCH_FILE)).toBeDefined(),
    );
    await fireEvent.input(casterInputs(first.container)[0], {
      target: { value: "ann" },
    });
    first.unmount();

    const second = render(CastSetup, {
      props: { race: showcaseRace("race-c2", 2), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(second.container, MATCH_FILE)).toBeDefined(),
    );
    expect(casterInputs(second.container)[0].value).toBe("");
  });

  it("warns while the field is not settled", async () => {
    serveGroupG(["alice", null, "carol", "dave"]);
    const unsettled = render(CastSetup, {
      props: { race: inGroupG("race-u1", 1), onClose: () => {} },
    });
    await waitFor(() =>
      expect(textOf(unsettled.container)).toContain(UNSETTLED),
    );
    unsettled.unmount();

    serveGroupG(["alice", "bob", "carol", "dave"]);
    const settled = render(CastSetup, {
      props: { race: inGroupG("race-u2", 2), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(settled.container, MATCH_FILE)).toBeDefined(),
    );
    expect(textOf(settled.container)).not.toContain(UNSETTLED);
  });

  // The caster downloads the match file again once a seat's runner is known,
  // often from a panel left open since before: the file reads the field
  // afresh, and the hint follows.
  it("a second match download seats a runner who arrived meanwhile", async () => {
    serveGroupG(["alice", null, "carol", "dave"]);
    const { container } = render(CastSetup, {
      props: { race: inGroupG("race-f1", 1), onClose: () => {} },
    });
    await waitFor(() => expect(textOf(container)).toContain(UNSETTLED));
    await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
    await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(1));

    serveGroupG(["alice", "bob", "carol", "dave"]);
    await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
    await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(2));

    const calls = vi.mocked(downloadJson).mock.calls as [string, Obj][];
    expect(plateUrl(calls[0][1], "Quad")).toContain("&p4=-&");
    expect(plateUrl(calls[1][1], "Quad")).toContain(
      "?p1=alice&p2=bob&p3=carol&p4=dave&",
    );
    expect(textOf(container)).not.toContain(UNSETTLED);
  });

  it("a match download builds from the field loaded when the refetch fails", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    const { container } = render(CastSetup, {
      props: { race: inGroupG("race-f2", 1), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(container, MATCH_FILE)).toBeDefined(),
    );
    vi.mocked(fetchEvent).mockRejectedValue(new Error("offline"));
    await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
    await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(1));

    const collection = vi.mocked(downloadJson).mock.calls[0][1] as Obj;
    expect(plateUrl(collection, "Quad")).toContain(
      "?p1=alice&p2=bob&p3=carol&p4=dave&",
    );
  });

  it("a match file draws its duels from the runners who race", async () => {
    // Five seats, one forfeited: four runners race, so every pair gets its
    // duel, as on any field of four.
    serveGroupG(["alice", "bob", "carol", "dave", "erin"], {
      forfeited: ["bob"],
    });
    const { container } = render(CastSetup, {
      props: { race: inGroupG("race-d1", 1), onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(container, MATCH_FILE)).toBeDefined(),
    );
    await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
    await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(1));

    const collection = vi.mocked(downloadJson).mock.calls[0][1] as Obj;
    const duels = collection.scene_order.filter((s: Obj) =>
      s.name.startsWith("Duel"),
    );
    expect(duels).toHaveLength(6);
  });

  // Above four runners the one duel is the pair the panel's duel holes
  // seat, resolved over POV 1 and 2's pins alone: alice, pinned in POV 3,
  // auto-fills POV 1 there, as the duel scene itself would seat her.
  it("both files' duel above four is the duel holes' pair", async () => {
    serveGroupG(["alice", "bob", "carol", "dave", "erin"]);
    const race = inGroupG("race-d5", 1);
    race.participants = [
      ...race.participants,
      fakeParticipant("p5", "erin", 4),
    ] as RaceDetail["participants"];
    const { container } = render(CastSetup, {
      props: { race, onClose: () => {} },
    });
    await waitFor(() =>
      expect(buttonLabelled(container, MATCH_FILE)).toBeDefined(),
    );
    const pov3 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[2];
    await fireEvent.change(pov3, { target: { value: "alice" } });
    await fireEvent.click(buttonLabelled(container, RACE_FILE)!);
    await fireEvent.click(buttonLabelled(container, MATCH_FILE)!);
    await waitFor(() => expect(downloadJson).toHaveBeenCalledTimes(2));

    for (const [, collection] of vi.mocked(downloadJson).mock.calls as [
      string,
      Obj,
    ][]) {
      const duels = collection.scene_order
        .map((s: Obj) => s.name)
        .filter((n: string) => n.startsWith("Duel"));
      expect(duels).toEqual(["Duel: alice vs bob"]);
      expect(plateUrl(collection, "Duel: alice vs bob")).toContain(
        "?p1=alice&p2=bob&",
      );
    }
  });

  it("the race file names every seat, under the race's own URLs", async () => {
    const { container } = render(CastSetup, {
      props: { race: fakeRace("race-file"), onClose: () => {} },
    });
    const pov2 =
      container.querySelectorAll<HTMLSelectElement>(".hole-grid select")[1];
    await fireEvent.change(pov2, { target: { value: "dave" } });
    await fireEvent.click(buttonLabelled(container, RACE_FILE)!);

    const [fileName, collection] = vi.mocked(downloadJson).mock.calls[0] as [
      string,
      Obj,
    ];
    expect(fileName).toBe("speedfog-race-race-fil.json");
    // The auto holes are written out, so the plate seats exactly the runners
    // whose POV sources sit under it, whoever joins later.
    expect(plateUrl(collection, "Quad")).toContain(
      "/overlay/cast/race/race-file/quad?p1=alice&p2=dave&p3=bob&p4=carol&",
    );
    // No event and stage chosen: no talk scene, Quad opens the file.
    expect(collection.scene_order[0].name).toBe("Quad");
  });

  it("the race file opens on talk once the panel has an event and a stage", async () => {
    serveGroupG(["alice", "bob", "carol", "dave"]);
    const { container } = render(CastSetup, {
      props: { race: inGroupG("race-t1", 1), onClose: () => {} },
    });
    await fireEvent.click(buttonLabelled(container, RACE_FILE)!);

    const collection = vi.mocked(downloadJson).mock.calls[0][1] as Obj;
    expect(collection.scene_order[0].name).toBe("Talk");
    expect(plateUrl(collection, "Talk")).toContain(
      "/overlay/cast/event/season-one/group_g/talk?",
    );
    expect(plateUrl(collection, "Quad")).toContain(
      "/overlay/cast/race/race-t1/quad?",
    );
  });
});
