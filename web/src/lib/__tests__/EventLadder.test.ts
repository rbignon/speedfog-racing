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
    entries,
  };
}

describe("EventLadder filters", () => {
  it("shows the empty-ladder message when there are no entries at all", () => {
    const { getByText } = render(EventLadder, {
      ladder: ladderWith([]),
      modes,
      viewerId: null,
      note: "",
    });
    expect(getByText("No runs yet.")).toBeTruthy();
  });

  it("shows the no-match message when filters exclude every entry", async () => {
    const { getByPlaceholderText, getByText } = render(EventLadder, {
      ladder: ladderWith([entry()]),
      modes,
      viewerId: null,
      note: "",
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
      note: "",
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
      note: "",
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
      note: "",
    });
    await fireEvent.click(getByText("Ranked only"));
    expect(queryByText("Ranked")).toBeTruthy();
    expect(queryByText("Unranked")).toBeNull();
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
      note: "",
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
      note: "",
    });
    expect(getByText("1/2")).toBeTruthy();
  });
});
