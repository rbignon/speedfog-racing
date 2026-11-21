import { describe, expect, it } from "vitest";

import type { RelayTeam } from "$lib/api";
import type { RelayMember, WsParticipant } from "$lib/websocket";
import {
  isValidRelayTeamSize,
  needsRaceRefetch,
  ownLiveRow,
  ownRunStatus,
  relayCap,
  relayCapSentence,
  relayCapacity,
  relayChoiceFor,
  relayHolderLine,
  relayMemberLabel,
  relayMemberState,
  relayRuleLine,
  relayStartBlocker,
  startingRunnerId,
  teamChoiceOptions,
  teamSlotAction,
  teamView,
} from "$lib/relay";

function team(over: Partial<RelayTeam> = {}): RelayTeam {
  return {
    id: "t1",
    name: "Team 1",
    color_index: 0,
    placeholder: false,
    first_runner_id: null,
    member_ids: [],
    ...over,
  };
}

describe("relayCap", () => {
  it("computes ceil(layers / members) + 1 like the server", () => {
    expect([
      relayCap(30, 3),
      relayCap(12, 3),
      relayCap(13, 3),
      relayCap(30, 2),
      relayCap(30, 6),
    ]).toEqual([11, 5, 6, 16, 6]);
  });

  it("counts a team with no active member as one", () => {
    expect(relayCap(12, 0)).toBe(13);
  });
});

describe("relayCapSentence", () => {
  it("writes the cap for the pool's zone count and the team size", () => {
    expect(relayCapSentence(30, 3)).toBe(
      "30 zones, teams of 3: 11 zones max per runner.",
    );
  });

  it("says nothing without a zone count", () => {
    expect([
      relayCapSentence(null, 3),
      relayCapSentence(undefined, 3),
      relayCapSentence(0, 3),
    ]).toEqual([null, null, null]);
  });
});

describe("isValidRelayTeamSize", () => {
  it("accepts integers from 2 to 6 only", () => {
    const accepted = [null, 1, 2, 6, 7, 2.5, 0].map(isValidRelayTeamSize);
    expect(accepted).toEqual([false, false, true, true, false, false, false]);
  });

  it("gives no cap sentence for an invalid size", () => {
    expect(relayCapSentence(30, 1)).toBeNull();
    expect(relayCapSentence(30, null)).toBeNull();
  });
});

describe("teamSlotAction", () => {
  const visitor = { participantTeamId: null, canRegister: true };

  it("offers Join to a visitor and Move to a runner of another team", () => {
    expect(teamSlotAction(team({ member_ids: ["a"] }), 3, visitor)).toBe(
      "join",
    );
    expect(
      teamSlotAction(team({ id: "t2", member_ids: ["a"] }), 3, {
        participantTeamId: "t1",
        canRegister: true,
      }),
    ).toBe("move");
  });

  it("offers nothing on the viewer's own team, a full team, or to someone who cannot register", () => {
    expect(
      teamSlotAction(team({ id: "t1", member_ids: ["a"] }), 3, {
        participantTeamId: "t1",
        canRegister: true,
      }),
    ).toBeNull();
    expect(
      teamSlotAction(team({ member_ids: ["a", "b", "c"] }), 3, visitor),
    ).toBeNull();
    expect(
      teamSlotAction(team(), 3, {
        participantTeamId: null,
        canRegister: false,
      }),
    ).toBeNull();
  });
});

describe("relayCapacity", () => {
  const four = [team(), team(), team(), team()];

  it("counts in teams once runners cannot create them", () => {
    expect(relayCapacity(four, 3, false, 30)).toBe(12);
  });

  it("falls back to the open-registration maximum, else null", () => {
    expect(relayCapacity(four, 3, true, 30)).toBe(30);
    expect(relayCapacity(four, 3, true, null)).toBeNull();
  });
});

describe("relayStartBlocker", () => {
  const two = team({ id: "a", name: "Red", member_ids: ["a1", "a2"] });
  const one = team({ id: "b", name: "Blue", member_ids: ["b1", "b2"] });
  const ready = { a1: "ready", a2: "ready", b1: "ready", b2: "registered" };

  it("needs two teams with members, empty placeholders left out", () => {
    const placeholder = team({ id: "c", placeholder: true });
    expect(relayStartBlocker([two, placeholder], ready)).toBe(
      "At least 2 teams are required to start a relay race",
    );
    expect(relayStartBlocker([], ready)).toBe(
      "At least 2 teams are required to start a relay race",
    );
  });

  it("names the first team short of two ready runners", () => {
    expect(relayStartBlocker([two, one], ready)).toBe(
      "Blue needs at least 2 ready runners",
    );
  });

  it("lets the race start when every team with members has two ready", () => {
    const placeholder = team({ id: "c", placeholder: true });
    expect(
      relayStartBlocker([two, one, placeholder], { ...ready, b2: "ready" }),
    ).toBeNull();
  });
});

describe("startingRunnerId", () => {
  it("is the chosen runner, else the first member", () => {
    expect(startingRunnerId(team({ member_ids: ["a", "b"] }))).toBe("a");
    expect(
      startingRunnerId(team({ member_ids: ["a", "b"], first_runner_id: "b" })),
    ).toBe("b");
  });

  it("ignores a chosen runner who left, and an empty team has none", () => {
    expect(
      startingRunnerId(team({ member_ids: ["a"], first_runner_id: "gone" })),
    ).toBe("a");
    expect(startingRunnerId(team())).toBeNull();
  });
});

describe("teamView", () => {
  it("groups the participants by team, in team order, members in team order", () => {
    const view = teamView(
      [
        team({ id: "t1", member_ids: ["b", "a"] }),
        team({ id: "t2", member_ids: [] }),
      ],
      [{ id: "a" }, { id: "b" }, { id: "stray" }],
    );
    expect(view.map((v) => [v.team.id, v.members.map((m) => m.id)])).toEqual([
      ["t1", ["b", "a"]],
      ["t2", []],
    ]);
  });
});

describe("teamChoiceOptions", () => {
  const teams = [
    team({ id: "a", name: "Red", member_ids: ["x"] }),
    team({ id: "b", name: "Blue", member_ids: ["x", "y"] }),
    team({ id: "c", name: "Empty", placeholder: true }),
  ];

  it("lists the teams with a free slot, then New team when allowed", () => {
    expect(teamChoiceOptions(teams, 2, true)).toEqual([
      { value: "a", label: "Red (1/2)" },
      { value: "c", label: "Empty (0/2)" },
      { value: "new", label: "New team" },
    ]);
    expect(teamChoiceOptions(teams, 2, false).map((o) => o.value)).toEqual([
      "a",
      "c",
    ]);
  });

  it("turns a value into the request body", () => {
    expect(relayChoiceFor("a")).toEqual({ relay_team_id: "a" });
    expect(relayChoiceFor("new")).toEqual({ create_team: true });
  });
});

describe("ownLiveRow", () => {
  const row = (id: string, username: string, ids: string[] | null) => ({
    id,
    twitch_username: username,
    status: "playing",
    relay_members: ids?.map((participant_id) => ({
      participant_id,
      status: "playing",
    })),
  });
  const rows = [
    row("team-a", "team-a1", ["p1", "p2"]),
    row("team-b", "team-b1", ["p3"]),
    row("team-c", "team-c1", []),
  ];

  it("finds the team listing the participant", () => {
    expect(ownLiveRow(rows, "p3", "bob")?.id).toBe("team-b");
  });

  it("is null for a viewer no team lists, and a team with no members matches nobody", () => {
    expect(ownLiveRow(rows, "p9", "bob")).toBeNull();
  });

  it("falls back to the username on a solo race", () => {
    const solo = [row("s1", "alice", null), row("s2", "bob", null)];
    expect(ownLiveRow(solo, "p2", "bob")?.id).toBe("s2");
  });
});

describe("ownRunStatus", () => {
  const team = (own: string) => ({
    id: "t",
    twitch_username: "team-t",
    status: "playing",
    relay_members: [{ participant_id: "p1", status: own }],
  });

  it("is the member's own status once they are out, else the row's", () => {
    expect(ownRunStatus(team("abandoned"), "p1")).toBe("abandoned");
    expect(ownRunStatus(team("disqualified"), "p1")).toBe("disqualified");
    expect(ownRunStatus(team("ready"), "p1")).toBe("playing");
    expect(ownRunStatus(team("abandoned"), "other")).toBe("playing");
    expect(ownRunStatus(null, "p1")).toBeUndefined();
  });
});

describe("needsRaceRefetch", () => {
  const solo = [{ id: "a" }, { id: "b" }];
  const teams = [
    {
      id: "t1",
      relay_members: [{ participant_id: "a" }, { participant_id: "b" }],
    },
    { id: "t2", relay_members: [{ participant_id: "c" }] },
  ];

  it("compares runner ids on a solo race", () => {
    const base = { isRelay: false, raceStatus: "running", loaded: true };
    expect(needsRaceRefetch({ ...base, rows: solo, restIds: ["b", "a"] })).toBe(
      false,
    );
    expect(needsRaceRefetch({ ...base, rows: solo, restIds: ["a"] })).toBe(
      true,
    );
    expect(needsRaceRefetch({ ...base, rows: [], restIds: ["a"] })).toBe(false);
  });

  it("re-fetches on every replacement of a relay race in setup, once loaded", () => {
    const base = {
      isRelay: true,
      raceStatus: "setup",
      rows: teams,
      restIds: ["a", "b", "c"],
    };
    expect(needsRaceRefetch({ ...base, loaded: true })).toBe(true);
    expect(needsRaceRefetch({ ...base, loaded: false })).toBe(false);
  });

  it("re-fetches a running relay race only when its members changed", () => {
    const base = {
      isRelay: true,
      raceStatus: "running",
      loaded: true,
      rows: teams,
    };
    expect(needsRaceRefetch({ ...base, restIds: ["c", "a", "b"] })).toBe(false);
    expect(needsRaceRefetch({ ...base, restIds: ["a", "b", "c", "d"] })).toBe(
      true,
    );
    expect(needsRaceRefetch({ ...base, restIds: ["a", "b"] })).toBe(true);
  });
});

function member(over: Partial<RelayMember> = {}): RelayMember {
  return {
    participant_id: "a",
    name: "Kiofto",
    zones: 3,
    status: "playing",
    online: true,
    ready: false,
    validated: false,
    ...over,
  };
}

function teamRow(over: Partial<WsParticipant> = {}): WsParticipant {
  return {
    id: "t1",
    twitch_username: "red_team",
    twitch_display_name: "Red Team",
    status: "playing",
    current_zone: null,
    current_layer: 4,
    igt_ms: 1000,
    death_count: 0,
    color_index: 0,
    mod_connected: true,
    zone_history: null,
    relay_holder: "Kiofto",
    relay_holder_id: "a",
    relay_cap: 5,
    relay_members: [member()],
    ...over,
  };
}

describe("relayHolderLine", () => {
  it("writes the holder and the zone", () => {
    expect(relayHolderLine(teamRow(), "Leyndell")).toBe("Kiofto, Leyndell");
    expect(relayHolderLine(teamRow(), null)).toBe("Kiofto");
  });

  it("says offline instead of the zone when the holder has no connection", () => {
    expect(
      relayHolderLine(
        teamRow({ relay_holder: "Linlin_Tv", mod_connected: false }),
        "Raya Lucaria",
      ),
    ).toBe("Linlin_Tv offline");
  });

  it("says the baton is free when a playing team has no holder", () => {
    expect(
      relayHolderLine(
        teamRow({ relay_holder: null, relay_holder_id: null }),
        "Leyndell",
      ),
    ).toBe("Baton free");
  });

  it("has no line for a team that is not playing or a row that is not a team", () => {
    expect(relayHolderLine(teamRow({ status: "finished" }), "x")).toBeNull();
    expect(
      relayHolderLine(teamRow({ relay_members: undefined }), "x"),
    ).toBeNull();
  });
});

describe("relayMemberState", () => {
  it("tells the holder from the waiting and the out", () => {
    expect(relayMemberState(member(), "a")).toBe("playing");
    expect(relayMemberState(member({ participant_id: "b" }), "a")).toBe(
      "waiting",
    );
    expect(
      relayMemberState(
        member({ participant_id: "c", status: "abandoned" }),
        "a",
      ),
    ).toBe("out");
  });

  it("keeps a disqualified holder out, whatever the team does", () => {
    expect(relayMemberState(member({ status: "disqualified" }), "a")).toBe(
      "out",
    );
  });

  it("treats everyone as waiting when the baton is free", () => {
    expect(relayMemberState(member(), null)).toBe("waiting");
    expect(relayMemberState(member(), undefined)).toBe("waiting");
  });

  it("reads finished before the holder", () => {
    expect(relayMemberState(member({ status: "finished" }), "a")).toBe(
      "finished",
    );
  });
});

describe("relayMemberLabel", () => {
  it("adds offline to the holder and to a waiting member only", () => {
    expect(relayMemberLabel(member({ online: false }), "a")).toBe(
      "playing, offline",
    );
    expect(
      relayMemberLabel(member({ participant_id: "b", online: false }), "a"),
    ).toBe("waiting, offline");
    expect(
      relayMemberLabel(
        member({ participant_id: "b", status: "abandoned", online: false }),
        "a",
      ),
    ).toBe("out");
    expect(relayMemberLabel(member(), "a")).toBe("playing");
  });
});

describe("relayRuleLine", () => {
  it("writes the rule from the zone count, team size and cap", () => {
    expect(relayRuleLine(30, 3, 11)).toBe(
      "Relay: 30 zones, teams of 3, 11 zones max per runner on a full team (higher on a smaller one).",
    );
  });

  it("drops what the race does not give", () => {
    expect(relayRuleLine(null, 3, 11)).toBe(
      "Relay: teams of 3, 11 zones max per runner on a full team (higher on a smaller one).",
    );
    expect(relayRuleLine(30, 3, null)).toBe("Relay: 30 zones, teams of 3.");
  });
});
