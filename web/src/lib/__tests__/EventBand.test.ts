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
