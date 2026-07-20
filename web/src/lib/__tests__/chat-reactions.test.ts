import { describe, expect, it } from "vitest";
import { applyChatReactionUpdate } from "$lib/stores/race.svelte";
import type { ChatMessage, ChatReactionUpdateMessage } from "$lib/websocket";

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  type: "chat_message",
  channel: "participants",
  id: "m1",
  username: "alice",
  display_name: "Alice",
  avatar_url: null,
  role: "participant",
  dominant_trait: null,
  equipped_badge_id: null,
  equipped_name_template_id: null,
  message: "hello",
  timestamp: "2026-07-20T12:00:00+00:00",
  reply_to: null,
  reactions: [],
  ...overrides,
});

const update = (
  overrides: Partial<ChatReactionUpdateMessage> = {},
): ChatReactionUpdateMessage => ({
  type: "chat_reaction_update",
  channel: "participants",
  message_id: "m1",
  reactions: [{ emoji: "laugh", usernames: ["bob"] }],
  ...overrides,
});

describe("applyChatReactionUpdate", () => {
  it("replaces the reactions of the matching message", () => {
    const messages = [message({ id: "m0" }), message({ id: "m1" })];
    applyChatReactionUpdate(messages, update());
    expect(messages[1].reactions).toEqual([
      { emoji: "laugh", usernames: ["bob"] },
    ]);
    expect(messages[0].reactions).toEqual([]);
  });

  it("clears reactions when the update carries an empty list", () => {
    const messages = [
      message({ reactions: [{ emoji: "cry", usernames: ["alice"] }] }),
    ];
    applyChatReactionUpdate(messages, update({ reactions: [] }));
    expect(messages[0].reactions).toEqual([]);
  });

  it("ignores updates for unknown message ids", () => {
    const messages = [message()];
    applyChatReactionUpdate(messages, update({ message_id: "ghost" }));
    expect(messages[0].reactions).toEqual([]);
  });
});
