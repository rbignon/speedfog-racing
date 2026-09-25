import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastRaceCard from "$lib/components/cast/CastRaceCard.svelte";
import type { EventFieldSlot, EventStageRace, Race, User } from "$lib/api";

const rect = { x: 0, y: 0, w: 436, h: 412 };

function fakeUser(over: Partial<User> = {}): User {
  return {
    id: "u-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    twitch_avatar_url: null,
    equipped_name_template_id: null,
    ...over,
  };
}

function fakePreview(over: Record<string, unknown> = {}) {
  return {
    ...fakeUser(),
    placement: null,
    status: "playing",
    igt_ms: null,
    ...over,
  };
}

function fakeEntry(
  raceOver: Record<string, unknown>,
  index = 1,
): EventStageRace {
  return {
    slot: "r1",
    index,
    race: {
      status: "running",
      participant_previews: [],
      ...raceOver,
    } as unknown as Race,
  };
}

describe("CastRaceCard: per-runner result", () => {
  it("shows a finisher's time and leaves an unfinished runner's cell blank", () => {
    const entry = fakeEntry({
      status: "finished",
      participant_previews: [
        fakePreview({ id: "p1", status: "finished", igt_ms: 72_000 }),
        fakePreview({ id: "p2", status: "playing", igt_ms: null }),
      ],
    });
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: "Standard", entry, field: [] },
    });
    const rows = container.querySelectorAll(".brow");
    expect(rows[0].querySelector(".bp")?.textContent).toBe("1:12");
    expect(rows[0].querySelector(".bp")?.classList.contains("prov")).toBe(
      false,
    );
    expect(rows[1].querySelector(".bp")?.textContent).toBe("");
    expect(rows[1].querySelector(".bp")?.classList.contains("prov")).toBe(true);
  });
});

describe("CastRaceCard: no race attached yet", () => {
  it("renders the stage's expected field, marking an undecided seat as TBD", () => {
    const field: EventFieldSlot[] = [
      {
        user: fakeUser({
          id: "u1",
          twitch_username: "bob",
          twitch_display_name: "Bob",
        }),
        label: "Top 2 of Quarter C",
      },
      { user: null, label: "Top 2 of Quarter C" },
    ];
    const { container } = render(CastRaceCard, {
      props: {
        rect,
        slot: 3,
        mode: "UWYG Major Rush",
        entry: null,
        field,
      },
    });
    const rows = container.querySelectorAll(".brow");
    expect(rows[0].querySelector(".bn")?.textContent).toBe("Bob");
    expect(rows[0].querySelector(".bn")?.classList.contains("tbd")).toBe(false);
    expect(rows[1].querySelector(".bn")?.textContent).toBe(
      "Top 2 of Quarter C",
    );
    expect(rows[1].querySelector(".bn")?.classList.contains("tbd")).toBe(true);
  });
});

describe("CastRaceCard: status badge", () => {
  it.each([
    ["running", "live", "Live"],
    ["finished", "finished", "Finished"],
    ["setup", "upcoming", "Upcoming"],
  ])("maps race status %s to the %s badge", (raceStatus, cls, text) => {
    const entry = fakeEntry({ status: raceStatus, participant_previews: [] });
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: undefined, entry, field: [] },
    });
    const badge = container.querySelector(".bst");
    expect(badge?.classList.contains(cls)).toBe(true);
    expect(badge?.textContent).toBe(text);
  });

  it("shows Upcoming when no race is attached yet", () => {
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: undefined, entry: null, field: [] },
    });
    const badge = container.querySelector(".bst");
    expect(badge?.classList.contains("upcoming")).toBe(true);
    expect(badge?.textContent).toBe("Upcoming");
  });
});
