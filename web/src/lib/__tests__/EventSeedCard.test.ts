import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventSeedCard from "$lib/components/events/EventSeedCard.svelte";
import type { EventQualifierRace, EventMyResult, Race } from "$lib/api";

const now = new Date("2026-09-10T12:00:00Z");

function raceWith(overrides: Partial<Race> = {}): Race {
  return {
    id: "r1",
    name: "Seed 1",
    organizer: {
      id: "u-org",
      twitch_username: "org",
      twitch_display_name: "Org",
      twitch_avatar_url: null,
    },
    status: "setup",
    pool_name: null,
    is_public: true,
    open_registration: true,
    max_participants: null,
    created_at: "2026-09-01T10:00:00Z",
    scheduled_at: null,
    started_at: null,
    seeds_released_at: null,
    late_join_window_minutes: null,
    race_duration_minutes: null,
    registration_closes_at: null,
    race_ends_at: null,
    private_dag: false,
    deathless: false,
    custom_rules: null,
    daily_date: null,
    exclude_from_stats: false,
    participant_count: 0,
    participant_previews: [],
    casters: [],
    can_join: true,
    my_role: null,
    event_id: null,
    event_slot: null,
    ...overrides,
  };
}

function entryWith(
  raceOverrides: Partial<Race> = {},
  myResult: EventMyResult | null = null,
  closesAt: string | null = "2026-09-15T00:00:00Z",
): EventQualifierRace {
  return {
    slot: "qualifier:standard:1",
    mode: "standard",
    index: 1,
    race: raceWith(raceOverrides),
    closes_at: closesAt,
    my_result: myResult,
  };
}

describe("EventSeedCard state signal", () => {
  it("shows Open with a Play strip for an unplayed, open, joinable seed", () => {
    const { getByText, container } = render(EventSeedCard, {
      entry: entryWith(),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("Open")).toBeTruthy();
    expect(container.querySelector(".play-strip")).not.toBeNull();
  });

  it("shows Joined with no Play strip once the viewer registered but hasn't played", () => {
    const { getByText, container } = render(EventSeedCard, {
      entry: entryWith(
        {},
        {
          status: "joined",
          finished: false,
          rank: null,
          igt_ms: null,
          points: null,
          provisional: false,
        },
      ),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("Joined")).toBeTruthy();
    expect(container.querySelector(".play-strip")).toBeNull();
  });

  it("shows Playing with no Play strip while the viewer is mid-run", () => {
    const { getByText, container } = render(EventSeedCard, {
      entry: entryWith(
        {},
        {
          status: "playing",
          finished: false,
          rank: null,
          igt_ms: null,
          points: null,
          provisional: false,
        },
      ),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("Playing")).toBeTruthy();
    expect(container.querySelector(".play-strip")).toBeNull();
  });

  it("shows Done with the result line once the viewer finished", () => {
    const { getByText, container } = render(EventSeedCard, {
      entry: entryWith(
        {},
        {
          status: "done",
          finished: true,
          rank: 2,
          igt_ms: 754_000,
          points: 87,
          provisional: true,
        },
      ),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("Done")).toBeTruthy();
    expect(container.querySelector(".play-strip")).toBeNull();
    expect(container.querySelector(".seed-card.route-done")).not.toBeNull();
    const result = container.querySelector(".result");
    expect(result?.textContent).toContain("2nd");
    expect(result?.textContent).toContain("87 pts provisional");
  });

  it("shows DNF, not Done, for an abandoned run that still holds a rank", () => {
    const { getByText, queryByText, container } = render(EventSeedCard, {
      entry: entryWith(
        {},
        {
          status: "done",
          finished: false,
          rank: 14,
          igt_ms: 1_930_000,
          points: 40,
          provisional: true,
        },
      ),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("DNF")).toBeTruthy();
    expect(queryByText("Done")).toBeNull();
    expect(container.querySelector(".play-strip")).toBeNull();
    // A scored DNF validated the seed: it rides the done colour, not the open one.
    expect(container.querySelector(".seed-card.route-done")).not.toBeNull();
    expect(container.querySelector(".result.unscored")).toBeNull();
    const result = container.querySelector(".result")?.textContent ?? "";
    expect(result).toContain("DNF");
    expect(result).toContain("14th");
    expect(result).toContain("40 pts provisional");
  });

  it("shows DNF for an abandoned run without a rank", () => {
    const { container } = render(EventSeedCard, {
      entry: entryWith(
        {},
        {
          status: "done",
          finished: false,
          rank: null,
          igt_ms: null,
          points: null,
          provisional: false,
        },
      ),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(container.querySelector(".result")?.textContent).toContain("DNF");
    // No score, so nothing validated: the spent grey line and a muted result.
    expect(container.querySelector(".seed-card.route-spent")).not.toBeNull();
    expect(container.querySelector(".result.unscored")).not.toBeNull();
  });

  it("shows Closed with no Play strip once the window has passed, even if unplayed", () => {
    const { getByText, container } = render(EventSeedCard, {
      entry: entryWith({}, null, "2026-09-01T00:00:00Z"),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("Closed")).toBeTruthy();
    expect(container.querySelector(".play-strip")).toBeNull();
  });

  it("hides the Play strip when the race itself refuses joins", () => {
    const { container } = render(EventSeedCard, {
      entry: entryWith({ can_join: false }),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(container.querySelector(".play-strip")).toBeNull();
  });

  it("caps avatar previews and shows the overflow count", () => {
    const previews = Array.from({ length: 5 }, (_, i) => ({
      id: `u${i}`,
      twitch_username: `p${i}`,
      twitch_display_name: null,
      twitch_avatar_url: null,
      placement: null,
      status: "registered" as const,
      igt_ms: null,
    }));
    const { getByText } = render(EventSeedCard, {
      entry: entryWith({
        participant_count: 8,
        participant_previews: previews,
      }),
      index: 1,
      modeLabel: "Standard",
      partner: null,
      now,
    });
    expect(getByText("+3")).toBeTruthy();
  });
});

describe("EventSeedCard placeholder", () => {
  it("renders an unlinked placeholder with the opening date when there is no race", () => {
    const { container, getByText } = render(EventSeedCard, {
      entry: null,
      index: 2,
      modeLabel: "Standard",
      partner: null,
      now,
      opensAt: "2026-09-23T17:00:00Z",
    });
    expect(container.querySelector("a")).toBeNull();
    expect(getByText("Standard - Seed 2")).toBeTruthy();
    expect(getByText(/^Opens /)).toBeTruthy();
  });
});
