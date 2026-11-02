import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import MetroDagProgressive from "$lib/dag/MetroDagProgressive.svelte";

const GRAPH = {
  total_layers: 2,
  nodes: {
    start: { type: "start", display_name: "Chapel of Anticipation", layer: 0 },
    boss: { type: "final_boss", display_name: "Starscourge Radahn", layer: 1 },
  },
  edges: [{ from: "start", to: "boss" }],
};

function mount(extra: Record<string, unknown> = {}) {
  return render(MetroDagProgressive, {
    props: {
      graphJson: GRAPH,
      participants: [],
      myParticipantId: "me",
      ...extra,
    },
  });
}

describe("MetroDagProgressive overlay options", () => {
  it("follows the runner through the follow viewport only when asked", () => {
    expect(mount().container.querySelector(".follow-container")).toBeNull();
    expect(
      mount({ follow: true }).container.querySelector(".follow-container"),
    ).not.toBeNull();
  });

  it("names only the discovered zones when following", () => {
    const { container } = mount({ follow: true });

    expect(container.textContent).toContain("Chapel of Anticipation");
    expect(container.textContent).not.toContain("Starscourge Radahn");
  });
});
