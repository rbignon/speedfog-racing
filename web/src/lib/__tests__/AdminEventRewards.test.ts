import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor, screen } from "@testing-library/svelte";
import AdminEventRewards from "$lib/components/events/AdminEventRewards.svelte";
import {
  fetchAdminEventRewards,
  grantAdminEventRewards,
  type EventRewardBlock,
  type EventRewards,
  type User,
} from "$lib/api";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return {
    ...actual,
    fetchAdminEventRewards: vi.fn(),
    grantAdminEventRewards: vi.fn(),
  };
});

function fakeUser(name: string): User {
  return {
    id: `u-${name}`,
    twitch_username: name,
    twitch_display_name: null,
    twitch_avatar_url: null,
  } as User;
}

function block(overrides: Partial<EventRewardBlock>): EventRewardBlock {
  return {
    bracket_key: "main",
    bracket_label: "Main",
    role: "seated",
    waiting: null,
    rewards: [{ kind: "badge", id: "season_1_qualifier", name: "Kindled" }],
    unknown_rewards: [],
    recipients: [
      { user: fakeUser("alice"), owned: [] },
      { user: fakeUser("bob"), owned: [] },
      { user: fakeUser("carol"), owned: [] },
    ],
    banned: [],
    new_grants: 3,
    ...overrides,
  };
}

const fixture: EventRewards = {
  blocks: [
    block({}),
    block({
      role: "champion",
      waiting: "stage_incomplete",
      recipients: [],
      new_grants: 0,
    }),
    block({
      bracket_key: "newcomers",
      bracket_label: "Newcomers",
      recipients: [
        { user: fakeUser("dave"), owned: ["badge:season_1_qualifier"] },
      ],
      new_grants: 0,
    }),
  ],
};

function grantButton(heading: string): HTMLButtonElement {
  const section = screen.getByText(heading).closest("section");
  return section!.querySelector("button.grant-btn") as HTMLButtonElement;
}

describe("AdminEventRewards", () => {
  beforeEach(() => {
    vi.mocked(fetchAdminEventRewards).mockReset();
    vi.mocked(grantAdminEventRewards).mockReset();
    vi.mocked(fetchAdminEventRewards).mockResolvedValue(fixture);
  });

  it("disables Grant on a waiting block and says why", async () => {
    render(AdminEventRewards, { eventId: "ev-1", onClose: () => {} });
    await screen.findByText("Main: champion");
    expect(grantButton("Main: champion").disabled).toBe(true);
    expect(
      screen.getByText("Waiting: the bracket's last stage is not complete."),
    ).toBeTruthy();
  });

  it("disables Grant when nothing in the block is new", async () => {
    render(AdminEventRewards, { eventId: "ev-1", onClose: () => {} });
    await screen.findByText("Newcomers: qualifiers");
    expect(grantButton("Newcomers: qualifiers").disabled).toBe(true);
    expect(grantButton("Main: qualifiers").disabled).toBe(false);
  });

  it("grants one block and reports the count", async () => {
    vi.mocked(grantAdminEventRewards).mockResolvedValue({
      granted: 3,
      block: block({ new_grants: 0 }),
    });
    render(AdminEventRewards, { eventId: "ev-1", onClose: () => {} });
    await screen.findByText("Main: qualifiers");
    await fireEvent.click(grantButton("Main: qualifiers"));
    await screen.findByText("Granted 3");
    expect(grantAdminEventRewards).toHaveBeenCalledTimes(1);
    expect(grantAdminEventRewards).toHaveBeenCalledWith(
      "ev-1",
      "main",
      "seated",
    );
    await waitFor(() =>
      expect(fetchAdminEventRewards).toHaveBeenCalledTimes(2),
    );
  });
});
