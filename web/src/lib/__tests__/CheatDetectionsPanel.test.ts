import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import CheatDetectionsPanel from "$lib/components/CheatDetectionsPanel.svelte";

const detections = {
  p1: {
    no_death: {
      detected_at: "2026-10-30T00:00:00Z",
      igt_ms: 1000,
      node_id: null,
    },
  },
};
const participants = [
  {
    id: "p1",
    twitch_username: "runner",
    twitch_display_name: "Runner",
    status: "playing",
  },
] as never;

describe("CheatDetectionsPanel action", () => {
  it("is labelled Disqualify by default and passes the runner and reason", async () => {
    const onDisqualify = vi.fn();
    const { getByText } = render(CheatDetectionsPanel, {
      detections,
      participants,
      onDisqualify,
    });

    await fireEvent.click(getByText("Disqualify"));

    expect(onDisqualify).toHaveBeenCalledWith(
      "p1",
      expect.stringContaining("Cheat tool"),
    );
  });

  it("takes the label of another action", () => {
    const { getByText, queryByText } = render(CheatDetectionsPanel, {
      detections,
      participants,
      onDisqualify: vi.fn(),
      actionLabel: "Invalidate",
    });

    expect(getByText("Invalidate")).toBeTruthy();
    expect(queryByText("Disqualify")).toBeNull();
  });
});
