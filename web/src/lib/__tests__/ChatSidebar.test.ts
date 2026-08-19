import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import ChatSidebar from "$lib/components/ChatSidebar.svelte";
import type { ChatMessage } from "$lib/websocket";

// Sheet mode mounts ZoneSheet, whose $effect fetches zone stats; keep
// the tests offline.
vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, fetchZoneDetail: vi.fn(() => new Promise(() => {})) };
});

function msg(
  channel: "participants" | "public",
  role: string,
  text: string,
  ts = "2026-05-10T10:00:00Z",
): ChatMessage {
  return {
    type: "chat_message",
    channel,
    username: role === "system" ? "" : "alice",
    display_name: role === "system" ? null : "Alice",
    avatar_url: null,
    role,
    dominant_trait: null,
    message: text,
    timestamp: ts,
  };
}

const baseProps = {
  canSend: true,
  currentUsername: null,
  participantsAccess: true,
  publicAccess: "readable" as const,
  activeTab: "participants" as const,
  historyVersion: 1,
  onSend: () => {},
  onReact: () => {},
  onToggle: () => {},
  onTabChange: () => {},
};

describe("ChatSidebar unread badges", () => {
  it("does not raise the collapsed badge when only system messages arrive", async () => {
    const { container, rerender } = render(ChatSidebar, {
      props: {
        ...baseProps,
        messagesParticipants: [],
        messagesPublic: [],
        collapsed: true,
      },
    });

    // System messages on either channel should not raise the badge.
    await rerender({
      ...baseProps,
      messagesParticipants: [msg("participants", "system", "Alice joined")],
      messagesPublic: [msg("public", "system", "Race started")],
      collapsed: true,
    });
    expect(container.querySelector(".unread-badge")).toBeNull();

    // A real user message should raise it.
    await rerender({
      ...baseProps,
      messagesParticipants: [
        msg("participants", "system", "Alice joined"),
        msg("participants", "participant", "hi"),
      ],
      messagesPublic: [msg("public", "system", "Race started")],
      collapsed: true,
    });
    expect(container.querySelector(".unread-badge")?.textContent).toBe("1");
  });

  it("does not raise the per-tab badge for system messages on the inactive tab", async () => {
    const { container, rerender } = render(ChatSidebar, {
      props: {
        ...baseProps,
        messagesParticipants: [],
        messagesPublic: [],
        collapsed: false,
        activeTab: "participants",
      },
    });

    // System message on the public (inactive) tab should not raise its badge.
    await rerender({
      ...baseProps,
      messagesParticipants: [],
      messagesPublic: [msg("public", "system", "Race started")],
      collapsed: false,
      activeTab: "participants",
    });
    expect(container.querySelector(".tab-badge")).toBeNull();

    // A real user message on the inactive tab should raise it.
    await rerender({
      ...baseProps,
      messagesParticipants: [],
      messagesPublic: [
        msg("public", "system", "Race started"),
        msg("public", "participant", "gg"),
      ],
      collapsed: false,
      activeTab: "participants",
    });
    expect(container.querySelector(".tab-badge")?.textContent?.trim()).toBe(
      "1",
    );
  });

  it("does not raise the badge when chat history reloads with mixed messages", async () => {
    const { container, rerender } = render(ChatSidebar, {
      props: {
        ...baseProps,
        messagesParticipants: [],
        messagesPublic: [],
        collapsed: true,
        historyVersion: 1,
      },
    });

    // chat_history replay (e.g. reconnect or public-chat unlock) brings in
    // a backlog that mixes system events with prior user messages: the
    // badge must stay at 0 because nothing arrived "after" the user's
    // last seen state.
    await rerender({
      ...baseProps,
      messagesParticipants: [
        msg("participants", "system", "Alice joined"),
        msg("participants", "participant", "hi"),
      ],
      messagesPublic: [
        msg("public", "system", "Race started"),
        msg("public", "participant", "gg"),
        msg("public", "system", "Bob finished"),
      ],
      collapsed: true,
      historyVersion: 2,
    });
    expect(container.querySelector(".unread-badge")).toBeNull();
  });

  it("keeps accruing unread while the zone sheet covers the chat", async () => {
    const zoneSheet = {
      nodeId: "stormveil_c3d4",
      displayName: "Stormveil",
      zones: ["stormveil"],
    };
    const { container, rerender } = render(ChatSidebar, {
      props: {
        ...baseProps,
        messagesParticipants: [],
        messagesPublic: [],
        collapsed: false,
        zoneSheet,
      },
    });
    expect(container.querySelector(".back-btn .tab-badge")).toBeNull();

    // A user message arriving while the sheet is open must raise the
    // sheet header's badge even though the sidebar is not collapsed.
    await rerender({
      ...baseProps,
      messagesParticipants: [msg("participants", "participant", "hi")],
      messagesPublic: [],
      collapsed: false,
      zoneSheet,
    });
    expect(
      container.querySelector(".back-btn .tab-badge")?.textContent?.trim(),
    ).toBe("1");

    // And keep growing as more messages arrive.
    await rerender({
      ...baseProps,
      messagesParticipants: [
        msg("participants", "participant", "hi"),
        msg("participants", "participant", "anyone?"),
      ],
      messagesPublic: [msg("public", "participant", "gg")],
      collapsed: false,
      zoneSheet,
    });
    expect(
      container.querySelector(".back-btn .tab-badge")?.textContent?.trim(),
    ).toBe("3");
  });

  it("resets the active tab's unread when the zone sheet closes", async () => {
    const zoneSheet = {
      nodeId: "stormveil_c3d4",
      displayName: "Stormveil",
      zones: ["stormveil"],
    };
    const { container, rerender } = render(ChatSidebar, {
      props: {
        ...baseProps,
        messagesParticipants: [],
        messagesPublic: [],
        collapsed: false,
        activeTab: "participants",
        zoneSheet,
      },
    });

    // Messages accrue on the active tab while the sheet is open.
    await rerender({
      ...baseProps,
      messagesParticipants: [msg("participants", "participant", "hi")],
      messagesPublic: [],
      collapsed: false,
      activeTab: "participants",
      zoneSheet,
    });
    expect(
      container.querySelector(".back-btn .tab-badge")?.textContent?.trim(),
    ).toBe("1");

    // Back to chat: the active tab is visible again, so its unread clears
    // and no badge remains anywhere.
    await rerender({
      ...baseProps,
      messagesParticipants: [msg("participants", "participant", "hi")],
      messagesPublic: [],
      collapsed: false,
      activeTab: "participants",
      zoneSheet: null,
    });
    expect(container.querySelector(".tab-badge")).toBeNull();
  });
});
