import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventBand from "$lib/components/events/EventBand.svelte";
import type { EventStage, EventSummary, Race, User } from "$lib/api";

function summaryWith(partial: Partial<EventSummary>): EventSummary {
  return {
    slug: "season-one",
    name: "Season One",
    partner_name: "Ignite",
    partner_logo_url: null,
    starts_at: "2026-09-23T08:00:00Z",
    qualifier_ends_at: "2026-09-30T08:00:00Z",
    ends_at: "2026-10-26T00:00:00Z",
    phase: "qualifier",
    my_signup: false,
    players: 3,
    player_previews: [],
    next_stage: null,
    live: null,
    champion: null,
    brackets: [],
    ...partial,
  };
}

function links(container: HTMLElement): Record<string, string> {
  const out: Record<string, string> = {};
  for (const a of container.querySelectorAll<HTMLAnchorElement>("a")) {
    out[a.textContent?.trim() ?? ""] = a.getAttribute("href") ?? "";
  }
  return out;
}

const runner = (id: string): User => ({
  id,
  twitch_username: id,
  twitch_display_name: null,
  twitch_avatar_url: null,
});

/** Semi A with its first race running, cast by karssi; ana leads on 100. */
function semiOnAir(): EventStage {
  const race = {
    id: "r1",
    status: "running",
    casters: [
      { id: "c1", user: runner("karssi"), is_live: false, stream_url: null },
    ],
    participant_previews: [],
    scheduled_at: null,
    started_at: "2026-10-18T17:02:00Z",
    finished_at: null,
    seed_total_layers: 9,
  } as unknown as Race;
  return {
    key: "semi_a",
    label: "Semi A",
    kind: "semi",
    bracket: "main",
    date: null,
    date_fixed: false,
    time_set: true,
    from: [],
    advance: 2,
    races_expected: 3,
    complete: false,
    walkover: false,
    modes: ["Standard", "Boss Rush", "UWYG"],
    races: [{ slot: "semi_a:1", index: 1, race, points: {}, live: [] }],
    results: [
      {
        user: runner("ana"),
        newcomer: false,
        points: 100,
        igt_total: 1_000_000,
        advances: false,
      },
    ],
    settled_results: [],
    field: [
      {
        user: runner("ana"),
        label: "Seed 1",
        forfeited: false,
        source: null,
        place: null,
      },
    ],
  } as unknown as EventStage;
}

describe("EventBand", () => {
  it("tells a signed-up viewer they are in instead of asking again", () => {
    const { container } = render(EventBand, {
      event: summaryWith({ my_signup: true }),
    });
    expect(container.textContent).toContain("You're in");
    expect(links(container)["Take part"]).toBeUndefined();
    expect(links(container)["Event page"]).toBe("/events/season-one");
  });

  it("links the whole lockup to the event page", () => {
    const { container } = render(EventBand, { event: summaryWith({}) });
    const lockup = container.querySelector("h2 a");
    expect(lockup?.getAttribute("href")).toBe("/events/season-one");
    expect(lockup?.textContent).toContain("Ignite");
    expect(lockup?.textContent).toContain("Season One");
  });

  it("stacks the players' avatars, initials without one, and counts the rest", () => {
    const player_previews = [
      {
        id: "u1",
        twitch_username: "ana",
        twitch_display_name: "Ana",
        twitch_avatar_url: "https://cdn.test/ana.png",
      },
      {
        id: "u2",
        twitch_username: "bob",
        twitch_display_name: null,
        twitch_avatar_url: null,
      },
    ] as User[];
    const { container } = render(EventBand, {
      event: summaryWith({ players: 11, player_previews }),
    });
    const stack = container.querySelector(".avatar-stack");
    expect(stack).not.toBeNull();
    expect(stack?.querySelector("img")?.getAttribute("title")).toBe("Ana");
    expect(stack?.querySelector(".avatar-placeholder")?.textContent).toBe("B");
    expect(stack?.querySelector(".avatar-overflow")?.textContent).toBe("+9");
    expect(container.textContent).not.toContain("11 in");
  });

  it("drops the stack once the event can no longer be joined", () => {
    const { container } = render(EventBand, {
      event: summaryWith({
        phase: "cut",
        players: 11,
        player_previews: [
          {
            id: "u1",
            twitch_username: "ana",
            twitch_display_name: "Ana",
            twitch_avatar_url: null,
          },
        ] as User[],
      }),
    });
    expect(container.querySelector(".avatar-stack")).toBeNull();
  });

  it("greys the eliminated and the forfeits in their seat, the others untouched", () => {
    const qualified = [
      {
        id: "u1",
        twitch_username: "ana",
        twitch_display_name: "Ana",
        twitch_avatar_url: "https://cdn.test/ana.png",
      },
      {
        id: "u2",
        twitch_username: "bob",
        twitch_display_name: null,
        twitch_avatar_url: null,
      },
      {
        id: "u3",
        twitch_username: "cid",
        twitch_display_name: "Cid",
        twitch_avatar_url: "https://cdn.test/cid.png",
      },
      {
        id: "u4",
        twitch_username: "dee",
        twitch_display_name: "Dee",
        twitch_avatar_url: null,
      },
    ] as User[];
    const { container } = render(EventBand, {
      event: summaryWith({
        phase: "playoffs",
        brackets: [
          {
            key: "main",
            label: "Top 32",
            qualified,
            eliminated: ["u2", "u1"],
            // bob withdrew, then sat out the stage that knocked him out.
            forfeited: ["u4", "u2"],
          },
        ],
      }),
    });
    const seats = [...container.querySelectorAll(".bracket-row .avatar")];
    // Seed order holds; the server's order of the ids does not matter.
    expect(seats.map((s) => s.getAttribute("title"))).toEqual([
      "Ana (eliminated)",
      "bob (forfeit)",
      "Cid",
      "Dee (forfeit)",
    ]);
    expect(seats.map((s) => s.classList.contains("out"))).toEqual([
      true,
      true,
      false,
      true,
    ]);
  });

  it("crowns the champion as a link to their profile", () => {
    const champion = {
      id: "u1",
      twitch_username: "ana",
      twitch_display_name: "Ana",
      twitch_avatar_url: null,
    } as User;
    const { container } = render(EventBand, {
      event: summaryWith({ phase: "finished", champion }),
    });
    expect(container.textContent).toContain("Champion");
    expect(links(container)["Ana"]).toBe("/user/ana");
  });

  it("gives each match on air a block without its table, casters in a line", () => {
    const { container } = render(EventBand, {
      event: summaryWith({
        phase: "playoffs",
        on_air_stages: [semiOnAir()],
        caster_languages: { karssi: "FR" },
      }),
    });
    const blocks = container.querySelectorAll(".match");
    expect(blocks.length).toBe(1);
    expect(blocks[0].querySelector("table")).toBeNull();
    expect(blocks[0].textContent).toContain("100 pts");
    expect(blocks[0].querySelector(".cast")?.textContent).toContain("FR");
    const to = links(container);
    expect(to["Race page"]).toBe("/race/r1");
    expect(to["Watch"]).toBe("https://twitch.tv/karssi");
    expect(to["Watch on Twitch"]).toBeUndefined();
  });

  it("shows no match block outside the playoffs, nor from an older server", () => {
    const finished = render(EventBand, {
      event: summaryWith({ phase: "finished", on_air_stages: [semiOnAir()] }),
    });
    expect(finished.container.querySelector(".match")).toBeNull();
    // A server from before the blocks sends no on-air stages at all.
    const older = render(EventBand, {
      event: summaryWith({ phase: "playoffs" }),
    });
    expect(older.container.querySelector(".match")).toBeNull();
  });
});
