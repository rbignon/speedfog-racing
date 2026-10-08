import { render, fireEvent } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventLadder from "$lib/components/events/EventLadder.svelte";
import type {
  EventLadder as EventLadderData,
  EventLadderEntry,
  EventMode,
} from "$lib/api";

const modes: EventMode[] = [
  { key: "standard", label: "Standard" },
  { key: "hard", label: "Hard" },
];

function entry(overrides: Partial<EventLadderEntry> = {}): EventLadderEntry {
  return {
    rank: 1,
    user: {
      id: "u1",
      twitch_username: "alice",
      twitch_display_name: "Alice",
      twitch_avatar_url: null,
    },
    newcomer: false,
    withdrawn: false,
    forfeited: false,
    mode_points: { standard: 100, hard: 90 },
    total: 190,
    modes_scored: 2,
    igt_total: 1000,
    provisional: false,
    ...overrides,
  };
}

function ladderWith(entries: EventLadderEntry[]): EventLadderData {
  return {
    provisional: false,
    entered: entries.length,
    ranked_count: entries.length,
    signed_up: 0,
    entries,
  };
}

describe("EventLadder filters", () => {
  it("shows the empty-ladder message when there are no entries at all", () => {
    const { getByText } = render(EventLadder, {
      ladder: ladderWith([]),
      modes,
      viewerId: null,
    });
    expect(getByText("No runs yet.")).toBeTruthy();
  });

  it("shows the no-match message when filters exclude every entry", async () => {
    const { getByPlaceholderText, getByText } = render(EventLadder, {
      ladder: ladderWith([entry()]),
      modes,
      viewerId: null,
    });
    const input = getByPlaceholderText("Find a runner");
    await fireEvent.input(input, { target: { value: "nobody-matches" } });
    expect(getByText("No runner matches your filters.")).toBeTruthy();
  });

  it("filters by username or display name, case-insensitively", async () => {
    const { getByPlaceholderText, queryByText } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          user: {
            id: "u1",
            twitch_username: "alice",
            twitch_display_name: "Alice",
            twitch_avatar_url: null,
          },
        }),
        entry({
          user: {
            id: "u2",
            twitch_username: "bobby",
            twitch_display_name: "Bob",
            twitch_avatar_url: null,
          },
        }),
      ]),
      modes,
      viewerId: null,
    });
    const input = getByPlaceholderText("Find a runner");
    await fireEvent.input(input, { target: { value: "BOB" } });
    expect(queryByText("Bob")).toBeTruthy();
    expect(queryByText("Alice")).toBeNull();
  });

  it("the Newcomers chip keeps only newcomer rows", async () => {
    const { getByText, queryByText } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          user: {
            id: "u1",
            twitch_username: "vet",
            twitch_display_name: "Vet",
            twitch_avatar_url: null,
          },
          newcomer: false,
        }),
        entry({
          user: {
            id: "u2",
            twitch_username: "rookie",
            twitch_display_name: "Rookie",
            twitch_avatar_url: null,
          },
          newcomer: true,
        }),
      ]),
      modes,
      viewerId: null,
    });
    await fireEvent.click(getByText("Newcomers"));
    expect(queryByText("Rookie")).toBeTruthy();
    expect(queryByText("Vet")).toBeNull();
  });

  it("the Ranked only chip drops entries with no rank", async () => {
    const { getByText, queryByText } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          rank: 1,
          user: {
            id: "u1",
            twitch_username: "ranked",
            twitch_display_name: "Ranked",
            twitch_avatar_url: null,
          },
        }),
        entry({
          rank: null,
          user: {
            id: "u2",
            twitch_username: "unranked",
            twitch_display_name: "Unranked",
            twitch_avatar_url: null,
          },
        }),
      ]),
      modes,
      viewerId: null,
    });
    await fireEvent.click(getByText("Ranked only"));
    expect(queryByText("Ranked")).toBeTruthy();
    expect(queryByText("Unranked")).toBeNull();
  });
});

describe("EventLadder qualification cut", () => {
  function user(id: string, name: string) {
    return {
      id,
      twitch_username: name.toLowerCase(),
      twitch_display_name: name,
      twitch_avatar_url: null,
    };
  }
  const field = [
    entry({ rank: 1, user: user("u1", "First") }),
    entry({ rank: 2, user: user("u2", "Second"), newcomer: true }),
    entry({ rank: 3, user: user("u3", "Third"), newcomer: true }),
  ];

  it("draws the cut line under the last qualifying row", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith(field),
      modes,
      viewerId: null,
      spots: 2,
    });
    const cut = container.querySelector(".cut");
    expect(cut).not.toBeNull();
    expect(cut?.textContent).toContain("Qualification");
    expect(cut?.previousElementSibling?.textContent).toContain("Second");
  });

  it("draws no line when the event declares no spots", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith(field),
      modes,
      viewerId: null,
    });
    expect(container.querySelector(".cut")).toBeNull();
  });

  it("draws no line when no visible row sits past the cut", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith(field),
      modes,
      viewerId: null,
      spots: 3,
    });
    expect(container.querySelector(".cut")).toBeNull();
  });

  it("the line follows the active filters", async () => {
    const { container, getByText } = render(EventLadder, {
      ladder: ladderWith(field),
      modes,
      viewerId: null,
      spots: 2,
    });
    await fireEvent.click(getByText("Newcomers"));
    const cut = container.querySelector(".cut");
    expect(cut).not.toBeNull();
    expect(cut?.previousElementSibling?.textContent).toContain("Second");
  });

  it("cuts a boundary-spanning tie positionally, as seeding does", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith([
        entry({ rank: 1, user: user("u1", "First") }),
        entry({ rank: 1, user: user("u2", "Second") }),
        entry({ rank: 1, user: user("u3", "Third") }),
      ]),
      modes,
      viewerId: null,
      spots: 2,
    });
    const cut = container.querySelector(".cut");
    expect(cut).not.toBeNull();
    expect(cut?.previousElementSibling?.textContent).toContain("Second");
  });

  it("moves up to the previous qualifying row when a filter hides the boundary row", async () => {
    const { container, getByText } = render(EventLadder, {
      ladder: ladderWith([
        entry({ rank: 1, user: user("u1", "First"), newcomer: true }),
        entry({ rank: 2, user: user("u2", "Second") }),
        entry({ rank: 3, user: user("u3", "Third"), newcomer: true }),
      ]),
      modes,
      viewerId: null,
      spots: 2,
    });
    await fireEvent.click(getByText("Newcomers"));
    const cut = container.querySelector(".cut");
    expect(cut).not.toBeNull();
    expect(cut?.previousElementSibling?.textContent).toContain("First");
  });

  it("draws the line between the qualifying rows and the unranked tail", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith([
        entry({ rank: 1, user: user("u1", "First") }),
        entry({
          rank: null,
          total: null,
          modes_scored: 0,
          user: user("u2", "Signup"),
        }),
      ]),
      modes,
      viewerId: null,
      spots: 2,
    });
    const cut = container.querySelector(".cut");
    expect(cut).not.toBeNull();
    expect(cut?.previousElementSibling?.textContent).toContain("First");
  });
});

describe("EventLadder rows", () => {
  it("highlights the viewer's own row", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          user: {
            id: "me",
            twitch_username: "me",
            twitch_display_name: "Me",
            twitch_avatar_url: null,
          },
        }),
      ]),
      modes,
      viewerId: "me",
    });
    expect(container.querySelector(".row.me")).not.toBeNull();
  });

  it("shows modes-scored progress instead of a total when the runner hasn't scored every mode", () => {
    const { getByText } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          total: null,
          modes_scored: 1,
          mode_points: { standard: 100, hard: null },
        }),
      ]),
      modes,
      viewerId: null,
    });
    expect(getByText("1/2")).toBeTruthy();
  });

  it("leaves a struck runner without a number and tags a forfeit", () => {
    const { container } = render(EventLadder, {
      ladder: ladderWith([
        entry({
          rank: null,
          withdrawn: true,
          user: { ...entry().user, id: "u2", twitch_username: "bob" },
        }),
        entry({ rank: 2, forfeited: true }),
      ]),
      modes,
      viewerId: null,
    });
    const rows = container.querySelectorAll(".row.withdrawn");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".rank")?.textContent).toBe("");
    expect(rows[1].querySelector(".rank")?.textContent).toBe("2");
    expect(rows[1].textContent).toContain("forfeit");
  });
});
