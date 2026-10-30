import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));

import InvitePage from "../../routes/invite/[token]/+page.svelte";
import type { InviteInfo, RunMode } from "$lib/api";

const WARNING = "Set Seed race: other runners may have practiced this seed";

function renderInvite(raceMode: RunMode) {
  const invite: InviteInfo = {
    token: "t1",
    race_name: "Friday race",
    organizer_name: "Org",
    race_status: "setup",
    race_mode: raceMode,
    twitch_username: "runner",
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
});
