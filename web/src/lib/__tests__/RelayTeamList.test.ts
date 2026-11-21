import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

vi.mock("$lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/api")>()),
  joinRelayTeam: vi.fn(),
  deleteRelayTeam: vi.fn(),
  createRelayTeam: vi.fn(),
  fetchRace: vi.fn(),
}));

import RelayTeamList from "$lib/components/RelayTeamList.svelte";
import {
  fetchRace,
  joinRelayTeam,
  type Participant,
  type RelayTeam,
} from "$lib/api";

function participant(id: string, teamId: string | null): Participant {
  return {
    id,
    relay_team_id: teamId,
    user: {
      id: `u-${id}`,
      twitch_username: id,
      twitch_display_name: id,
      twitch_avatar_url: null,
    },
    status: "registered",
    current_layer: 0,
    igt_ms: 0,
    death_count: 0,
    color_index: 0,
  };
}

function team(over: Partial<RelayTeam>): RelayTeam {
  return {
    id: "t1",
    name: "Red",
    color_index: 0,
    placeholder: false,
    first_runner_id: null,
    member_ids: [],
    ...over,
  };
}

const teams = [
  team({ id: "t1", name: "Red", member_ids: ["alice", "bob"] }),
  team({ id: "t2", name: "Blue", member_ids: ["carol"] }),
  team({ id: "t3", name: "Empty", placeholder: true }),
];
const participants = [
  participant("alice", "t1"),
  participant("bob", "t1"),
  participant("carol", "t2"),
];

function renderList(
  over: {
    runnersCreateTeams?: boolean;
    viewer?: Partial<{
      participantId: string | null;
      isOrganizer: boolean;
      canRegister: boolean;
    }>;
  } = {},
) {
  const onChanged = vi.fn();
  render(RelayTeamList, {
    props: {
      raceId: "race1",
      organizerUserId: "u-org",
      teams,
      participants: participants.map((p) => ({ ...p, liveStatus: undefined })),
      teamSize: 3,
      runnersCreateTeams: over.runnersCreateTeams ?? true,
      viewer: {
        participantId: null,
        isOrganizer: false,
        canRegister: true,
        ...over.viewer,
      },
      onChanged,
      onRemove: vi.fn(),
    },
  });
  return { onChanged };
}

beforeEach(() => vi.clearAllMocks());

describe("RelayTeamList", () => {
  it("hides + Create a team from a runner once the organizer turned it off", () => {
    renderList({ runnersCreateTeams: false });
    expect(screen.queryByText("+ Create a team")).toBeNull();
  });

  it("keeps + Create a team for the organizer whatever the setting", () => {
    renderList({
      runnersCreateTeams: false,
      viewer: { isOrganizer: true, participantId: "alice" },
    });
    expect(screen.getByText("+ Create a team")).toBeTruthy();
  });

  it("hides Delete from a runner", () => {
    renderList({ viewer: { participantId: "alice" } });
    expect(screen.queryByText("Delete")).toBeNull();
  });

  it("offers the organizer Delete on the empty team alone", () => {
    renderList({ viewer: { isOrganizer: true, participantId: "alice" } });
    expect(screen.getAllByText("Delete")).toHaveLength(1);
  });

  it("names the default first runner when the team chose none", () => {
    renderList();
    expect(screen.getByText("alice", { selector: "strong" })).toBeTruthy();
  });

  it("moves the viewer when they click Move to this team", async () => {
    const moved = { id: "race" } as never;
    vi.mocked(joinRelayTeam).mockResolvedValue(moved);
    const { onChanged } = renderList({ viewer: { participantId: "alice" } });
    // The first team with a free slot that is not the viewer's is Blue.
    await fireEvent.click(screen.getAllByText("Move to this team")[0]);
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledWith(moved));
    expect(joinRelayTeam).toHaveBeenCalledWith("race1", "t2");
  });

  it("re-reads the race after a refusal and keeps the message", async () => {
    const fresh = { id: "race1" } as never;
    vi.mocked(joinRelayTeam).mockRejectedValue(new Error("Team is full"));
    vi.mocked(fetchRace).mockResolvedValue(fresh);
    const { onChanged } = renderList({ viewer: { participantId: "alice" } });
    await fireEvent.click(screen.getAllByText("Move to this team")[0]);
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledWith(fresh));
    expect(screen.getByText("Team is full")).toBeTruthy();
  });
});
