import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventUpNext from "$lib/components/events/EventUpNext.svelte";
import type { EventStage, Race } from "$lib/api";

describe("EventUpNext", () => {
  it("still renders its casters for a server that sends no languages yet", () => {
    // During a deploy the new page can meet the old server's payload.
    const stage: EventStage = {
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
            casters: [
              {
                id: "c1",
                user: {
                  id: "u-karssi",
                  twitch_username: "karssi",
                  twitch_display_name: null,
                  twitch_avatar_url: null,
                },
                is_live: false,
                stream_url: null,
              },
            ],
          } as unknown as Race,
          points: {},
          live: [],
        },
      ],
      results: [],
      settled_results: [],
      field: [],
    };
    const { getByText } = render(EventUpNext, {
      match: { stage, at: stage.date as string, timeSet: true },
      stages: [stage],
      now: new Date("2026-10-12T12:00:00Z"),
    });
    expect(getByText("karssi")).toBeTruthy();
  });
});
