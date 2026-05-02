import { describe, expect, it, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import UserLink from "$lib/components/UserLink.svelte";
import { rewards } from "$lib/stores/rewards.svelte";

const seedCatalog = () => {
  rewards.catalog = {
    badges: [
      {
        id: "early_adopter",
        name: "Early Adopter",
        icon_filename: "early_adopter.svg",
        lifecycle: "permanent",
        sort_order: 10,
      },
    ],
    name_templates: [
      {
        id: "default",
        name: "Default",
        color: "#FFFFFF",
        gradient: null,
        name_css: null,
        background_css: null,
        sort_order: 0,
      },
      {
        id: "elo_crown",
        name: "ELO Crown",
        color: null,
        gradient: ["#FFE9A8", "#C8A44E"],
        name_css: "font-family: Georgia, serif; font-style: italic;",
        background_css: null,
        sort_order: 10,
      },
    ],
    phantom_skins: [],
  };
};

describe("UserLink", () => {
  beforeEach(() => {
    rewards.catalog = null;
  });

  it("renders the display name", () => {
    seedCatalog();
    const { getByText } = render(UserLink, {
      props: {
        user: {
          id: "u1",
          twitch_username: "alice",
          twitch_display_name: "Alice",
          twitch_avatar_url: null,
        },
      },
    });
    expect(getByText("Alice")).toBeTruthy();
  });

  it("falls back to status color when template is default or unset", () => {
    seedCatalog();
    const { container } = render(UserLink, {
      props: {
        user: {
          id: "u1",
          twitch_username: "alice",
          twitch_display_name: "Alice",
          twitch_avatar_url: null,
          equipped_name_template_id: "default",
        },
      },
    });
    // No special style applied: data-name-style should be "inherit".
    const nameSpan = container.querySelector(".user-link-name");
    expect(nameSpan?.getAttribute("data-name-style")).toBe("inherit");
  });

  it("applies gradient when a non-default template is equipped", () => {
    seedCatalog();
    const { container } = render(UserLink, {
      props: {
        user: {
          id: "u2",
          twitch_username: "bob",
          twitch_display_name: "Bob",
          twitch_avatar_url: null,
          equipped_name_template_id: "elo_crown",
        },
      },
    });
    const nameSpan = container.querySelector(".user-link-name");
    expect(nameSpan?.getAttribute("data-name-style")).toBe("gradient");
    const style = nameSpan?.getAttribute("style") ?? "";
    expect(style).toContain("linear-gradient");
    expect(style).toContain("#FFE9A8");
    expect(style).toContain("#C8A44E");
  });

  it("appends name_css to the inline style when provided", () => {
    seedCatalog();
    const { container } = render(UserLink, {
      props: {
        user: {
          id: "u5",
          twitch_username: "erin",
          twitch_display_name: "Erin",
          twitch_avatar_url: null,
          equipped_name_template_id: "elo_crown",
        },
      },
    });
    const style =
      container.querySelector(".user-link-name")?.getAttribute("style") ?? "";
    expect(style).toContain("Georgia");
    expect(style).toContain("italic");
  });

  it("renders a badge icon when showBadge is true and equipped", () => {
    seedCatalog();
    const { container } = render(UserLink, {
      props: {
        user: {
          id: "u3",
          twitch_username: "carol",
          twitch_display_name: "Carol",
          twitch_avatar_url: null,
          equipped_badge_id: "early_adopter",
        },
        showBadge: true,
      },
    });
    const img = container.querySelector("img.user-link-badge");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toContain("early_adopter.svg");
  });

  it("does NOT render badge icon when showBadge is false", () => {
    seedCatalog();
    const { container } = render(UserLink, {
      props: {
        user: {
          id: "u4",
          twitch_username: "dave",
          twitch_display_name: "Dave",
          twitch_avatar_url: null,
          equipped_badge_id: "early_adopter",
        },
        showBadge: false,
      },
    });
    expect(container.querySelector("img.user-link-badge")).toBeNull();
  });
});
