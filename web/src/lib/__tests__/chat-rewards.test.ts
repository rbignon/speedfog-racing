import { describe, expect, it, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import ChatPanel from "$lib/components/ChatPanel.svelte";
import { rewards } from "$lib/stores/rewards.svelte";
import type { ChatMessage } from "$lib/websocket";

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
        background_css:
          "radial-gradient(ellipse 60% 100% at 25% 50%, rgba(200,164,78,0.18), transparent 70%)",
        sort_order: 10,
      },
    ],
  };
};

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  type: "chat_message",
  channel: "participants",
  username: "alice",
  display_name: "Alice",
  avatar_url: null,
  role: "participant",
  dominant_trait: null,
  equipped_badge_id: null,
  equipped_name_template_id: null,
  message: "hello",
  timestamp: "2026-04-30T12:00:00+00:00",
  ...overrides,
});

describe("ChatPanel rewards integration", () => {
  beforeEach(() => {
    rewards.catalog = null;
  });

  it("applies gradient name style when an unlocked template is equipped", () => {
    seedCatalog();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message({ equipped_name_template_id: "elo_crown" })],
        canSend: false,
        onSend: () => {},
      },
    });
    const link = container.querySelector("a.display-name");
    expect(link?.getAttribute("style") ?? "").toContain("linear-gradient");
  });

  it("does not apply a name style when the template is default or absent", () => {
    seedCatalog();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message({ equipped_name_template_id: null })],
        canSend: false,
        onSend: () => {},
      },
    });
    const link = container.querySelector("a.display-name");
    expect(link?.getAttribute("style") ?? "").not.toContain("linear-gradient");
  });

  it("renders the equipped badge icon next to the name", () => {
    seedCatalog();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message({ equipped_badge_id: "early_adopter" })],
        canSend: false,
        onSend: () => {},
      },
    });
    const img = container.querySelector("img.reward-badge");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toContain("early_adopter.svg");
  });

  it("does not render a badge icon when no badge is equipped", () => {
    seedCatalog();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message({ equipped_badge_id: null })],
        canSend: false,
        onSend: () => {},
      },
    });
    expect(container.querySelector("img.reward-badge")).toBeNull();
  });
});
