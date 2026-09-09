import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventLiveStrip from "$lib/components/events/EventLiveStrip.svelte";
import type { Race } from "$lib/api";

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

function watchLink(container: HTMLElement): HTMLAnchorElement | undefined {
  return [...container.querySelectorAll("a")].find(
    (a) => a.textContent === "Watch on Twitch",
  ) as HTMLAnchorElement | undefined;
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
    expect(watchLink(container)).toBeUndefined();
  });
});
