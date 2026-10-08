import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import EventQualified from "$lib/components/events/EventQualified.svelte";
import type {
  EventBracket,
  EventQualified as EventQualifiedData,
  EventStage,
} from "$lib/api";

function stage(overrides: Partial<EventStage> = {}): EventStage {
  return {
    key: "semi-a",
    label: "Semi A",
    kind: "semi",
    bracket: "main",
    date: "2026-10-04T20:00:00Z",
    date_fixed: true,
    time_set: true,
    from: [],
    advance: null,
    races_expected: 3,
    complete: false,
    walkover: false,
    modes: ["standard"],
    races: [],
    results: [],
    field: new Array(8).fill(null).map(() => ({
      user: null,
      label: "TBD",
      forfeited: false,
    })),
    ...overrides,
  };
}

const stages: EventStage[] = [
  stage({ key: "semi-a", label: "Semi A", kind: "semi" }),
  stage({ key: "semi-b", label: "Semi B", kind: "semi" }),
  stage({
    key: "newcomers",
    label: "Newcomers' final",
    kind: "final",
    bracket: "newcomers",
  }),
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
        label: "Newcomers' final",
        entries: [{ seed: 1, user: null, newcomer: true, note: null }],
      },
    ],
    ...over,
  };
}

const fmt = (iso: string) => iso;

const bracket = (key: string, label: string): EventBracket => ({
  key,
  label,
  entry: key === "main" ? "all" : "newcomers",
  current_stage_key: null,
  next_stage: null,
});
const brackets = [bracket("main", "Top 32"), bracket("newcomers", "Newcomers")];

describe("EventQualified group titles", () => {
  it("titles each box with its stage's label and heads each bracket when there are several", () => {
    const { container } = render(EventQualified, {
      qualified: qualifiedWith(),
      stages,
      brackets,
      cutAt: "2026-10-08T08:00:00Z",
      formatDate: fmt,
    });
    expect(
      [...container.querySelectorAll(".bracket-label")].map(
        (n) => n.textContent,
      ),
    ).toEqual(["Top 32", "Newcomers"]);
    expect(
      [...container.querySelectorAll(".name")].map((n) => n.textContent),
    ).toEqual(["Semi A", "Semi B", "Newcomers' final"]);
  });

  it("shows no bracket heading for a single bracket", () => {
    const { container } = render(EventQualified, {
      qualified: qualifiedWith({ groups: qualifiedWith().groups.slice(0, 2) }),
      stages: stages.slice(0, 2),
      brackets: brackets.slice(0, 1),
      cutAt: "2026-10-08T08:00:00Z",
      formatDate: fmt,
    });
    expect(container.querySelector(".bracket-label")).toBeNull();
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
      brackets,
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
      brackets,
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
      brackets,
      cutAt: "2026-09-20T00:00:00Z",
      formatDate: fmt,
    });
    expect(getByText("Final")).toBeTruthy();
    expect(queryByText("Provisional")).toBeNull();
  });
});
