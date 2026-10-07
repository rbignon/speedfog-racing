import { fireEvent, render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import EventBracketTabs from "$lib/components/events/EventBracketTabs.svelte";
import type { EventBracket, EventStage } from "$lib/api";

const bracket = (key: string, label: string): EventBracket => ({
  key,
  label,
  entry: key === "main" ? "all" : "newcomers",
  current_stage_key: null,
  next_stage: null,
});
const brackets = [bracket("main", "Top 32"), bracket("newcomers", "Newcomers")];
const stageIn = (key: string, bracketKey: string, status: string) =>
  ({
    key,
    bracket: bracketKey,
    races: [{ race: { status } }],
  }) as unknown as EventStage;

describe("EventBracketTabs", () => {
  it("dots the tab of the bracket whose race runs, and only that one", () => {
    const { getAllByRole } = render(EventBracketTabs, {
      brackets,
      stages: [
        stageIn("semi_a", "main", "finished"),
        stageIn("newcomers_semi_a", "newcomers", "running"),
      ],
      selected: "main",
      onselect: () => {},
    });
    const tabs = getAllByRole("tab");
    expect(tabs.map((t) => t.querySelector(".live-dot") !== null)).toEqual([
      false,
      true,
    ]);
    expect(tabs.map((t) => t.getAttribute("aria-selected"))).toEqual([
      "true",
      "false",
    ]);
  });

  it("asks for the bracket clicked", async () => {
    const onselect = vi.fn();
    const { getAllByRole } = render(EventBracketTabs, {
      brackets,
      stages: [],
      selected: "main",
      onselect,
    });
    await fireEvent.click(getAllByRole("tab")[1]);
    expect(onselect).toHaveBeenCalledWith("newcomers");
  });
});
