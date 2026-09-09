import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventLiveStrip from "$lib/components/events/EventLiveStrip.svelte";
import type { EventStage, Race } from "$lib/api";

function raceWith(overrides: Partial<Race> = {}): Race {
  return {
    id: "r1",
    name: "Test Race",
    organizer: {
      id: "u1",
      twitch_username: "org",
      twitch_display_name: "Org",
      twitch_avatar_url: null,
    },
    status: "running",
    pool_name: null,
    is_public: true,
    open_registration: false,
    max_participants: null,
    created_at: "2026-08-01T10:00:00Z",
    scheduled_at: null,
    started_at: "2026-10-04T20:00:00Z",
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
    can_join: false,
    my_role: null,
    ...overrides,
  };
}

function stageWith(overrides: Partial<EventStage> = {}): EventStage {
  return {
    key: "semi_a",
    label: "Semi A",
    kind: "semi",
    date: "2026-10-04T20:00:00Z",
    races_expected: 3,
    complete: false,
    modes: [],
    races: [],
    results: [],
    field: [],
    ...overrides,
  };
}

function watchLink(container: HTMLElement): HTMLAnchorElement | null {
  return container.querySelector<HTMLAnchorElement>("a.btn-twitch");
}

describe("EventLiveStrip watch link", () => {
  it("prefers a live caster's own stream url over the twitch profile guess", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({
        casters: [
          {
            id: "c1",
            user: {
              id: "u2",
              twitch_username: "quiet",
              twitch_display_name: null,
              twitch_avatar_url: null,
            },
            is_live: false,
            stream_url: null,
          },
          {
            id: "c2",
            user: {
              id: "u3",
              twitch_username: "live-one",
              twitch_display_name: null,
              twitch_avatar_url: null,
            },
            is_live: true,
            stream_url: "https://twitch.tv/live-one/clip-embed",
          },
        ],
      }),
      stage: null,
      raceIndex: null,
    });
    expect(watchLink(container)?.href).toBe(
      "https://twitch.tv/live-one/clip-embed",
    );
  });

  it("falls back to the first caster's profile url when none is marked live", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({
        casters: [
          {
            id: "c1",
            user: {
              id: "u2",
              twitch_username: "caster1",
              twitch_display_name: null,
              twitch_avatar_url: null,
            },
            is_live: false,
            stream_url: null,
          },
        ],
      }),
      stage: null,
      raceIndex: null,
    });
    expect(watchLink(container)?.href).toBe("https://twitch.tv/caster1");
  });

  it("hides the watch button when the race has no casters", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({ casters: [] }),
      stage: null,
      raceIndex: null,
    });
    expect(watchLink(container)).toBeNull();
  });
});

describe("EventLiveStrip title and sub line", () => {
  it("joins the title from the stage, race index and pool name with a consistent separator", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({ pool_name: "sprint" }),
      stage: stageWith({ label: "Semi A", races_expected: 3 }),
      raceIndex: 2,
    });
    expect(container.querySelector(".title")?.textContent).toBe(
      "Semi A · Race 2 of 3 · Sprint",
    );
  });

  it("drops the stray leading dot when there are no runner previews to lead the sub line", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({ participant_previews: [] }),
      stage: null,
      raceIndex: null,
    });
    const sub = container.querySelector(".sub")?.textContent ?? "";
    expect(sub.startsWith("·")).toBe(false);
    expect(sub).toContain("started");
  });

  it("rounds the race duration cap to the nearest hour", () => {
    const { container } = render(EventLiveStrip, {
      race: raceWith({ race_duration_minutes: 90 }),
      stage: null,
      raceIndex: null,
    });
    expect(container.querySelector(".sub")?.textContent).toContain("cap 2h");
  });
});
