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

describe("CastRaceCard: row cap", () => {
  // rect is 436x412, the real per-slot race card rect from layout.ts's talk
  // scene: (412 - 95 header reserve) / 56 row height = 5 rows fit.
  function previews(n: number) {
    return Array.from({ length: n }, (_, i) =>
      fakePreview({ id: `p-${i}`, status: "playing", igt_ms: null }),
    );
  }

  it("shows every row and no overflow line when the field fits under capacity", () => {
    const entry = fakeEntry({ participant_previews: previews(3) });
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: "Standard", entry, field: [] },
    });
    expect(container.querySelectorAll(".brow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".brow")).toHaveLength(3);
  });

  it("shows every row and no overflow line when the field exactly fills capacity", () => {
    const entry = fakeEntry({ participant_previews: previews(5) });
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: "Standard", entry, field: [] },
    });
    expect(container.querySelectorAll(".brow.more")).toHaveLength(0);
    expect(container.querySelectorAll(".brow")).toHaveLength(5);
  });

  it("caps rows and reports the rest once the field exceeds capacity, never overflowing the card", () => {
    const entry = fakeEntry({ participant_previews: previews(8) });
    const { container } = render(CastRaceCard, {
      props: { rect, slot: 1, mode: "Standard", entry, field: [] },
    });
    const rows = container.querySelectorAll(".brow");
    expect(rows).toHaveLength(5); // 4 data rows + 1 overflow row
    const more = container.querySelector(".brow.more .more-text");
    expect(more?.textContent).toBe("+ 4 more");
  });
});

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
