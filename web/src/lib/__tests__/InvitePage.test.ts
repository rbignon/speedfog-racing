import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/api")>()),
  acceptInvite: vi.fn().mockResolvedValue({ race_id: "r1" }),
}));
vi.mock("$lib/stores/auth.svelte", () => ({
  auth: {
    initialized: true,
    isLoggedIn: true,
    user: { twitch_username: "runner" },
  },
}));

import InvitePage from "../../routes/invite/[token]/+page.svelte";
import { acceptInvite, type InviteInfo, type RunMode } from "$lib/api";

const WARNING = "Set Seed race: other runners may have practiced this seed";

function renderInvite(raceMode: RunMode, over: Partial<InviteInfo> = {}) {
  const invite: InviteInfo = {
    token: "t1",
    race_name: "Friday race",
    organizer_name: "Org",
    race_status: "setup",
    race_mode: raceMode,
    twitch_username: "runner",
    race_id: "r1",
    relay_team_size: null,
    relay_runners_create_teams: true,
    relay_teams: [],
    ...over,
  };
  return render(InvitePage, { props: { data: { invite } } as never });
}

// Accepting an invite joins the race: a Set Seed race says what the race
// page's own join asks first.
describe("invite page", () => {
  it("warns before a runner accepts a Set Seed race", () => {
    renderInvite("set_seed");
    expect(screen.getByText(WARNING)).toBeTruthy();
  });

  it("says nothing for the other races", () => {
    for (const mode of ["normal", "speedrun"] as RunMode[]) {
      const view = renderInvite(mode);
      expect(screen.queryByText(WARNING)).toBeNull();
      view.unmount();
    }
  });

  it("asks for a team before accepting an invite to a relay race", async () => {
    renderInvite("normal", {
      relay_team_size: 2,
      relay_teams: [
        {
          id: "full",
          name: "Full",
          color_index: 0,
          placeholder: false,
          first_runner_id: null,
          member_ids: ["a", "b"],
        },
        {
          id: "t2",
          name: "Blue",
          color_index: 1,
          placeholder: false,
          first_runner_id: null,
          member_ids: ["c"],
        },
      ],
    });
    const select = screen.getByLabelText("Team") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Blue (1/2)",
      "New team",
    ]);
    await fireEvent.change(select, { target: { value: "t2" } });
    await fireEvent.click(screen.getByText("Accept Invite"));
    expect(acceptInvite).toHaveBeenCalledWith("t1", { relay_team_id: "t2" });
  });

  it("offers no New team when runners may not create teams", () => {
    renderInvite("normal", {
      relay_team_size: 2,
      relay_runners_create_teams: false,
      relay_teams: [
        {
          id: "t2",
          name: "Blue",
          color_index: 1,
          placeholder: true,
          first_runner_id: null,
          member_ids: [],
        },
      ],
    });
    const select = screen.getByLabelText("Team") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Blue (0/2)",
    ]);
  });
});
