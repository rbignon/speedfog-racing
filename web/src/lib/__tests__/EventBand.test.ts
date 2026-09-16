import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventBand from "$lib/components/events/EventBand.svelte";
import type { EventSummary, User } from "$lib/api";

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

describe("EventBand", () => {
  it("tells a signed-up viewer they are in instead of asking again", () => {
    const { container } = render(EventBand, {
      event: summaryWith({ my_signup: true }),
    });
    expect(container.textContent).toContain("You're in");
    expect(links(container)["Take part"]).toBeUndefined();
    expect(links(container)["Event page"]).toBe("/events/season-one");
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
});
