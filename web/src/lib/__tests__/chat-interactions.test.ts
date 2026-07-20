import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/svelte";
import ChatPanel from "$lib/components/ChatPanel.svelte";
import type { ChatMessage } from "$lib/websocket";

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

describe("ChatPanel reactions and replies", () => {
  it("clicking a reaction pill toggles via onReact", async () => {
    const onReact = vi.fn();
    const { container } = render(ChatPanel, {
      props: {
        messages: [
          message({ reactions: [{ emoji: "laugh", usernames: ["bob"] }] }),
        ],
        canSend: true,
        currentUsername: "alice",
        onSend: () => {},
        onReact,
      },
    });
    const pill = container.querySelector("button.reaction-pill");
    expect(pill?.textContent).toContain("1");
    await fireEvent.click(pill!);
    expect(onReact).toHaveBeenCalledWith("m1", "laugh");
  });

  it("highlights the pill when the viewer has reacted", () => {
    const { container } = render(ChatPanel, {
      props: {
        messages: [
          message({ reactions: [{ emoji: "cry", usernames: ["alice"] }] }),
        ],
        canSend: true,
        currentUsername: "alice",
        onSend: () => {},
        onReact: () => {},
      },
    });
    expect(container.querySelector("button.reaction-pill.mine")).not.toBeNull();
  });

  it("reply flow: reply button arms the composer, submit passes replyTo", async () => {
    const onSend = vi.fn();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message()],
        canSend: true,
        currentUsername: "bob",
        onSend,
        onReact: () => {},
      },
    });
    await fireEvent.click(container.querySelector("button.action-reply")!);
    expect(container.querySelector(".reply-bar")?.textContent).toContain(
      "Alice",
    );
    const input =
      container.querySelector<HTMLInputElement>("input.chat-input")!;
    await fireEvent.input(input, { target: { value: "answering" } });
    await fireEvent.submit(container.querySelector("form.input-row")!);
    expect(onSend).toHaveBeenCalledWith("answering", "m1");
    expect(container.querySelector(".reply-bar")).toBeNull();
  });

  it("renders the quote and no toolbar on system messages", () => {
    const { container } = render(ChatPanel, {
      props: {
        messages: [
          message({
            id: "m2",
            reply_to: {
              id: "m1",
              username: "alice",
              display_name: "Alice",
              snippet: "hello",
            },
          }),
          message({ id: null, role: "system", message: "Race started" }),
        ],
        canSend: true,
        currentUsername: "bob",
        onSend: () => {},
        onReact: () => {},
      },
    });
    expect(container.querySelector(".reply-quote")?.textContent).toContain(
      "hello",
    );
    // one toolbar for the normal message, none for the system one
    expect(container.querySelectorAll(".msg-actions").length).toBe(1);
  });

  it("Escape cancels an armed reply without sending", async () => {
    const onSend = vi.fn();
    const { container } = render(ChatPanel, {
      props: {
        messages: [message()],
        canSend: true,
        currentUsername: "bob",
        onSend,
        onReact: () => {},
      },
    });
    await fireEvent.click(container.querySelector("button.action-reply")!);
    expect(container.querySelector(".reply-bar")).not.toBeNull();
    const input =
      container.querySelector<HTMLInputElement>("input.chat-input")!;
    await fireEvent.keyDown(input, { key: "Escape" });
    expect(container.querySelector(".reply-bar")).toBeNull();
    expect(onSend).not.toHaveBeenCalled();
  });

  it("hides the reaction/reply toolbar when the viewer cannot send", () => {
    const { container } = render(ChatPanel, {
      props: {
        messages: [
          message({ reactions: [{ emoji: "laugh", usernames: ["bob"] }] }),
        ],
        canSend: false,
        currentUsername: "alice",
        onSend: () => {},
        onReact: () => {},
      },
    });
    expect(container.querySelector(".msg-actions")).toBeNull();
  });
});
