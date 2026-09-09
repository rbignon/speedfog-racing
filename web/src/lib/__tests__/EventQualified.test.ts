import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventQualified from "$lib/components/events/EventQualified.svelte";
import type {
  EventQualified as EventQualifiedData,
  EventStage,
} from "$lib/api";

function stage(overrides: Partial<EventStage> = {}): EventStage {
  return {
    key: "semi-a",
    label: "Semi A",
    kind: "semi",
    date: "2026-10-04T20:00:00Z",
    races_expected: 3,
    complete: false,
    modes: ["standard"],
    races: [],
    results: [],
    field: new Array(8).fill(null).map(() => ({ user: null, label: "TBD" })),
    ...overrides,
  };
}

const stages: EventStage[] = [
  stage({ key: "semi-a", label: "Semi A", kind: "semi" }),
  stage({ key: "semi-b", label: "Semi B", kind: "semi" }),
  stage({ key: "newcomers", label: "Newcomers Final", kind: "newcomers" }),
];

function qualifiedWith(
  over: Partial<EventQualifiedData> = {},
): EventQualifiedData {
  return {
    provisional: true,
    groups: [
      {
        stage_key: "semi-a",
        label: "Semi A",
        entries: [{ seed: 1, user: null, newcomer: false, note: null }],
      },
      {
        stage_key: "semi-b",
        label: "Semi B",
        entries: [{ seed: 1, user: null, newcomer: false, note: null }],
      },
      {
        stage_key: "newcomers",
        label: "Newcomers",
        entries: [{ seed: 1, user: null, newcomer: true, note: null }],
      },
    ],
    ...over,
  };
}

const fmt = (iso: string) => iso;

describe("EventQualified group titles", () => {
  it("labels the first and second semi groups Group A and Group B in stage order", () => {
    const { getByText } = render(EventQualified, {
      qualified: qualifiedWith(),
      stages,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("Group A")).toBeTruthy();
    expect(getByText("Group B")).toBeTruthy();
  });

  it("labels the newcomers group Newcomers regardless of where the newcomers stage sits in the array", () => {
    const reordered: EventStage[] = [
      stage({ key: "newcomers", label: "Newcomers Final", kind: "newcomers" }),
      stage({ key: "semi-a", label: "Semi A", kind: "semi" }),
      stage({ key: "semi-b", label: "Semi B", kind: "semi" }),
    ];
    const { getByText } = render(EventQualified, {
      qualified: qualifiedWith(),
      stages: reordered,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("Newcomers")).toBeTruthy();
    expect(getByText("Group A")).toBeTruthy();
    expect(getByText("Group B")).toBeTruthy();
  });

  it("shows the filled/total count for a group", () => {
    const { getByText } = render(EventQualified, {
      qualified: qualifiedWith({
        groups: [
          {
            stage_key: "semi-a",
            label: "Semi A",
            entries: [
              {
                seed: 1,
                user: {
                  id: "u1",
                  twitch_username: "a",
                  twitch_display_name: null,
                  twitch_avatar_url: null,
                },
                newcomer: false,
                note: null,
              },
              { seed: 2, user: null, newcomer: false, note: null },
            ],
          },
        ],
      }),
      stages,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("1 / 2")).toBeTruthy();
  });
});

describe("EventQualified provisional banner", () => {
  it("shows Provisional and the cut date while the qualifier is still open", () => {
    const { getByText } = render(EventQualified, {
      qualified: qualifiedWith({ provisional: true }),
      stages,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("Provisional")).toBeTruthy();
    expect(getByText(/2026-09-20T00:00:00Z/)).toBeTruthy();
  });

  it("shows Final once the cut has locked the field", () => {
    const { getByText, queryByText } = render(EventQualified, {
      qualified: qualifiedWith({ provisional: false }),
      stages,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("Final")).toBeTruthy();
    expect(queryByText("Provisional")).toBeNull();
  });
});
