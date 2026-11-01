import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventUpNext from "$lib/components/events/EventUpNext.svelte";
import type { Caster, EventStage, Race } from "$lib/api";

describe("EventUpNext", () => {
  /** Group E's one race, cast by `casters`. */
  const groupE = (casters: Caster[]): EventStage => ({
    key: "group_e",
    label: "Group E",
    kind: "round",
    bracket: "main",
    date: "2026-10-17T14:00:00Z",
    date_fixed: false,
    time_set: true,
    from: [],
    advance: 2,
    races_expected: 1,
    complete: false,
    walkover: false,
    modes: ["Standard"],
    races: [
      {
        slot: "group_e:1",
        index: 1,
        race: {
          id: "r1",
          status: "setup",
          scheduled_at: "2026-10-17T14:00:00Z",
          casters,
        } as unknown as Race,
        points: {},
        live: [],
      },
    ],
    results: [],
    settled_results: [],
    field: [],
  });
  const karssi = {
    id: "c1",
    user: {
      id: "u-karssi",
      twitch_username: "karssi",
      twitch_display_name: null,
      twitch_avatar_url: null,
    },
    is_live: false,
    stream_url: null,
  };
  const renderBox = (stage: EventStage) =>
    render(EventUpNext, {
      match: { stage, at: stage.date as string, timeSet: true },
      stages: [stage],
      now: new Date("2026-10-12T12:00:00Z"),
    });

  it("still renders its casters for a server that sends no languages yet", () => {
    // During a deploy the new page can meet the old server's payload.
    const { getByText } = renderBox(groupE([karssi]));
    expect(getByText("karssi")).toBeTruthy();
  });

  it("links each caster to their channel, not their profile", () => {
    const { container } = renderBox(groupE([karssi]));
    const link = container.querySelector(".cast a");
    expect(link?.getAttribute("href")).toBe("https://twitch.tv/karssi");
  });

  it("announces the casters to come while none is named", () => {
    const { container, getByText } = renderBox(groupE([]));
    expect(getByText("Casters to be announced")).toBeTruthy();
    expect(container.querySelector(".cast a")).toBeNull();
  });
});
