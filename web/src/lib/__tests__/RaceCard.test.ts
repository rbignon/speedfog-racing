import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import RaceCard from "$lib/components/RaceCard.svelte";
import type { Race } from "$lib/api";

// Minimal race factory
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
    status: "setup",
    pool_name: "sprint",
    is_public: true,
    open_registration: false,
    max_participants: null,
    created_at: "2026-08-01T10:00:00Z",
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
    seed_total_layers: 10,
    my_participant_status: null,
    my_current_layer: null,
    my_igt_ms: null,
    my_death_count: null,
    can_join: false,
    my_role: null,
    ...overrides,
  };
}

function routeOf(container: HTMLElement): HTMLElement {
  const route = container.querySelector<HTMLElement>(".route");
  if (!route) throw new Error("no .route rendered");
  return route;
}

/* The route line reads from the viewer's seat: the same race renders
 * differently depending on their participation. */
describe("RaceCard route state", () => {
  it("shows a dashed grey setup line to a non-participant", () => {
    const { container } = render(RaceCard, { race: raceWith() });
    const route = routeOf(container);
    expect(route.classList.contains("route-setup")).toBe(true);
    expect(route.classList.contains("route-progress")).toBe(false);
    expect(route.querySelector(".m-pos")).toBeNull();
    expect(route.querySelector(".m-train")).toBeNull();
  });

  it("adds the waiting position dot for a registered viewer in setup", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        my_participant_status: "registered",
        my_role: "participating",
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-setup")).toBe(true);
    expect(route.classList.contains("route-progress")).toBe(true);
    expect(route.querySelector(".m-pos")).not.toBeNull();
    expect(route.getAttribute("style")).toContain("--route-progress: 0");
  });

  it("shows the ember traveling dot to a spectator of a running race", () => {
    const { container } = render(RaceCard, {
      race: raceWith({ status: "running", started_at: "2026-08-01T11:00:00Z" }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-running")).toBe(true);
    expect(route.querySelector(".m-train")).not.toBeNull();
    expect(route.querySelector(".m-pos")).toBeNull();
  });

  it("shows the viewer's clamped progress while they ride a running race", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        status: "running",
        started_at: "2026-08-01T11:00:00Z",
        my_participant_status: "playing",
        my_current_layer: 4,
        seed_total_layers: 10,
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-progress")).toBe(true);
    expect(route.classList.contains("route-setup")).toBe(false);
    expect(route.getAttribute("style")).toContain("--route-progress: 0.4");
    expect(route.querySelector(".m-train")).toBeNull();
  });

  it("keeps the frozen progress for a viewer who abandoned mid-race", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        status: "running",
        started_at: "2026-08-01T11:00:00Z",
        my_participant_status: "abandoned",
        my_current_layer: 25,
        seed_total_layers: 10,
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-progress")).toBe(true);
    // overflowing layer counts clamp to the terminal
    expect(route.getAttribute("style")).toContain("--route-progress: 1");
  });

  it("parks the dot at the start when the seed's layer count is unknown", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        status: "running",
        started_at: "2026-08-01T11:00:00Z",
        my_participant_status: "playing",
        my_current_layer: 4,
        seed_total_layers: null,
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-progress")).toBe(true);
    expect(route.getAttribute("style")).toContain("--route-progress: 0");
  });

  it("turns verdigris once the viewer finished a still-running race", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        status: "running",
        started_at: "2026-08-01T11:00:00Z",
        my_participant_status: "finished",
        my_current_layer: 10,
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-done")).toBe(true);
    expect(route.classList.contains("route-progress")).toBe(false);
  });

  it("turns steel for everyone once the race is over", () => {
    const { container } = render(RaceCard, {
      race: raceWith({
        status: "finished",
        started_at: "2026-08-01T11:00:00Z",
        my_participant_status: "finished",
        my_current_layer: 10,
      }),
    });
    const route = routeOf(container);
    expect(route.classList.contains("route-finished")).toBe(true);
    expect(route.classList.contains("route-progress")).toBe(false);
    expect(route.classList.contains("route-done")).toBe(false);
  });

  it("always draws both end markers", () => {
    for (const race of [
      raceWith(),
      raceWith({ status: "running", started_at: "2026-08-01T11:00:00Z" }),
      raceWith({ status: "finished", started_at: "2026-08-01T11:00:00Z" }),
    ]) {
      const { container } = render(RaceCard, { race });
      const route = routeOf(container);
      expect(route.querySelector(".m-start")).not.toBeNull();
      expect(route.querySelector(".m-end")).not.toBeNull();
    }
  });
});
