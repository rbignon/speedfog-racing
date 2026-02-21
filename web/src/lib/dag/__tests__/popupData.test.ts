import { describe, it, expect } from "vitest";
import {
  computeConnections,
  computePlayersAtNode,
  computeVisitors,
  formatIgt,
  parseExitTexts,
  parseEntranceTexts,
} from "../popupData";
import type { DagEdge, DagNode } from "../types";

// Minimal node factory
function node(id: string, layer = 0): DagNode {
  return {
    id,
    type: "mini_dungeon",
    displayName: id,
    zones: [],
    layer,
    tier: 1,
    weight: 1,
  };
}

const NODES: DagNode[] = [
  {
    id: "start",
    type: "start",
    displayName: "Chapel of Anticipation",
    zones: [],
    layer: 0,
    tier: 1,
    weight: 1,
  },
  node("stormveil", 1),
  node("liurnia", 2),
  node("raya", 2),
  node("caelid", 3),
];

const EDGES: DagEdge[] = [
  { from: "start", to: "stormveil" },
  { from: "stormveil", to: "liurnia" },
  { from: "stormveil", to: "raya" },
  { from: "liurnia", to: "caelid" },
  { from: "raya", to: "caelid" },
];

describe("computeConnections", () => {
  const nodeMap = new Map(NODES.map((n) => [n.id, n]));

  it("returns entrances and exits for a middle node", () => {
    const conns = computeConnections("stormveil", EDGES, nodeMap);
    expect(conns.entrances).toEqual([
      {
        nodeId: "start",
        displayName: "Chapel of Anticipation",
        type: "start",
      },
    ]);
    expect(conns.exits).toHaveLength(2);
    expect(conns.exits.map((e) => e.nodeId).sort()).toEqual([
      "liurnia",
      "raya",
    ]);
  });

  it("returns no entrances for start node", () => {
    const conns = computeConnections("start", EDGES, nodeMap);
    expect(conns.entrances).toHaveLength(0);
    expect(conns.exits).toHaveLength(1);
  });

  it("returns no exits for terminal node", () => {
    const conns = computeConnections("caelid", EDGES, nodeMap);
    expect(conns.exits).toHaveLength(0);
    expect(conns.entrances).toHaveLength(2);
  });

  it("filters by discoveredIds when provided", () => {
    const discovered = new Set(["start", "stormveil", "liurnia"]);
    const conns = computeConnections("stormveil", EDGES, nodeMap, discovered);
    expect(conns.entrances).toEqual([
      {
        nodeId: "start",
        displayName: "Chapel of Anticipation",
        type: "start",
      },
    ]);
    // raya is not discovered, so its displayName is null
    const raya = conns.exits.find((e) => e.nodeId === "raya");
    expect(raya?.displayName).toBeNull();
    // liurnia IS discovered
    const liurnia = conns.exits.find((e) => e.nodeId === "liurnia");
    expect(liurnia?.displayName).toBe("liurnia");
  });

  it("omits hidden connections (not discovered and not adjacent)", () => {
    // If discoveredIds only has "start", stormveil is adjacent but liurnia/raya are hidden
    const discovered = new Set(["start"]);
    const conns = computeConnections("start", EDGES, nodeMap, discovered);
    // stormveil is adjacent to start, so it should appear with null displayName
    expect(conns.exits).toHaveLength(1);
    expect(conns.exits[0].displayName).toBeNull();
  });
});

describe("computePlayersAtNode", () => {
  const participants = [
    {
      id: "p1",
      twitch_display_name: "Alice",
      twitch_username: "alice",
      status: "playing",
      current_zone: "stormveil",
      color_index: 0,
      igt_ms: 60000,
      death_count: 2,
      current_layer: 1,
      mod_connected: true,
      zone_history: null,
    },
    {
      id: "p2",
      twitch_display_name: "Bob",
      twitch_username: "bob",
      status: "playing",
      current_zone: "liurnia",
      color_index: 1,
      igt_ms: 90000,
      death_count: 0,
      current_layer: 2,
      mod_connected: true,
      zone_history: null,
    },
    {
      id: "p3",
      twitch_display_name: null,
      twitch_username: "charlie",
      status: "finished",
      current_zone: "stormveil",
      color_index: 2,
      igt_ms: 120000,
      death_count: 1,
      current_layer: 3,
      mod_connected: false,
      zone_history: null,
    },
  ];

  it("returns players at a specific node", () => {
    const players = computePlayersAtNode("stormveil", participants);
    expect(players).toHaveLength(2);
    expect(players[0].displayName).toBe("Alice");
    expect(players[1].displayName).toBe("charlie"); // falls back to username
  });

  it("returns empty for node with no players", () => {
    expect(computePlayersAtNode("caelid", participants)).toHaveLength(0);
  });
});

describe("computeVisitors", () => {
  const participants = [
    {
      id: "p1",
      twitch_display_name: "Alice",
      twitch_username: "alice",
      status: "finished",
      current_zone: "caelid",
      color_index: 0,
      igt_ms: 300000,
      death_count: 5,
      current_layer: 3,
      mod_connected: false,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "stormveil", igt_ms: 60000 },
        { node_id: "liurnia", igt_ms: 120000 },
        { node_id: "caelid", igt_ms: 200000 },
      ],
    },
    {
      id: "p2",
      twitch_display_name: "Bob",
      twitch_username: "bob",
      status: "finished",
      current_zone: "caelid",
      color_index: 1,
      igt_ms: 350000,
      death_count: 3,
      current_layer: 3,
      mod_connected: false,
      zone_history: [
        { node_id: "start", igt_ms: 0 },
        { node_id: "stormveil", igt_ms: 80000 },
        { node_id: "raya", igt_ms: 150000 },
        { node_id: "caelid", igt_ms: 250000 },
      ],
    },
  ];

  it("returns visitors sorted by arrival time with time spent", () => {
    const visitors = computeVisitors("stormveil", participants);
    expect(visitors).toHaveLength(2);
    expect(visitors[0].displayName).toBe("Alice");
    expect(visitors[0].arrivedAtMs).toBe(60000);
    expect(visitors[0].timeSpentMs).toBe(60000); // next zone (liurnia) at 120000
    expect(visitors[1].displayName).toBe("Bob");
    expect(visitors[1].arrivedAtMs).toBe(80000);
    expect(visitors[1].timeSpentMs).toBe(70000); // next zone (raya) at 150000
  });

  it("computes time spent using final IGT for last zone of finished participant", () => {
    const visitors = computeVisitors("caelid", participants);
    expect(visitors).toHaveLength(2);
    expect(visitors[0].arrivedAtMs).toBe(200000);
    expect(visitors[0].timeSpentMs).toBe(100000); // Alice: 300000 - 200000
    expect(visitors[1].arrivedAtMs).toBe(250000);
    expect(visitors[1].timeSpentMs).toBe(100000); // Bob: 350000 - 250000
  });

  it("computes time spent using current IGT for last zone of playing participant", () => {
    const playingParticipant = {
      ...participants[0],
      status: "playing",
      igt_ms: 250000,
    };
    const visitors = computeVisitors("caelid", [playingParticipant]);
    expect(visitors).toHaveLength(1);
    expect(visitors[0].timeSpentMs).toBe(50000); // 250000 - 200000
  });

  it("returns undefined timeSpentMs for last zone of non-playing/non-finished participant", () => {
    const readyParticipant = {
      ...participants[0],
      status: "ready",
      zone_history: [{ node_id: "start", igt_ms: 0 }],
    };
    const visitors = computeVisitors("start", [readyParticipant]);
    expect(visitors).toHaveLength(1);
    expect(visitors[0].timeSpentMs).toBeUndefined();
  });

  it("returns empty for unvisited node", () => {
    expect(computeVisitors("raya", [participants[0]])).toHaveLength(0);
  });

  it("includes deaths from zone_history entries", () => {
    const withDeaths = [
      {
        ...participants[0],
        zone_history: [
          { node_id: "start", igt_ms: 0, deaths: 1 },
          { node_id: "stormveil", igt_ms: 60000, deaths: 5 },
          { node_id: "liurnia", igt_ms: 120000 },
          { node_id: "caelid", igt_ms: 200000, deaths: 3 },
        ],
      },
    ];
    const stormveil = computeVisitors("stormveil", withDeaths);
    expect(stormveil[0].deaths).toBe(5);

    const liurnia = computeVisitors("liurnia", withDeaths);
    expect(liurnia[0].deaths).toBeUndefined(); // no deaths = undefined

    const caelid = computeVisitors("caelid", withDeaths);
    expect(caelid[0].deaths).toBe(3);
  });

  it("returns undefined deaths when field is missing (backward compat)", () => {
    // Original zone_history format without deaths field
    const visitors = computeVisitors("stormveil", participants);
    expect(visitors[0].deaths).toBeUndefined();
  });
});

describe("formatIgt", () => {
  it("formats minutes and seconds", () => {
    expect(formatIgt(65000)).toBe("1:05");
  });

  it("formats hours", () => {
    expect(formatIgt(3661000)).toBe("1:01:01");
  });

  it("handles zero", () => {
    expect(formatIgt(0)).toBe("0:00");
  });
});

describe("parseExitTexts", () => {
  it("extracts exit texts from graph.json nodes", () => {
    const graphJson = {
      nodes: {
        start: {
          type: "start",
          display_name: "Start",
          exits: [
            {
              fog_id: "fog1",
              text: "before the arena",
              from: "zone_a",
              to: "stormveil",
            },
            {
              fog_id: "fog2",
              text: "in the main room",
              from: "zone_b",
              to: "liurnia",
            },
          ],
        },
        stormveil: {
          type: "legacy_dungeon",
          display_name: "Stormveil",
          exits: [
            {
              fog_id: "fog3",
              text: "at the castle gate",
              from: "stormveil_zone",
              to: "caelid",
            },
          ],
        },
        liurnia: { type: "mini_dungeon", display_name: "Liurnia" },
      },
    };
    const map = parseExitTexts(graphJson);
    expect(map.size).toBe(2);
    expect(map.get("start")).toEqual([
      { text: "before the arena", toNodeId: "stormveil" },
      { text: "in the main room", toNodeId: "liurnia" },
    ]);
    expect(map.get("stormveil")).toEqual([
      { text: "at the castle gate", toNodeId: "caelid" },
    ]);
    expect(map.has("liurnia")).toBe(false);
  });

  it("returns empty map when no nodes", () => {
    expect(parseExitTexts({})).toEqual(new Map());
  });
});

describe("computeConnections with exitTexts", () => {
  const nodeMap = new Map(NODES.map((n) => [n.id, n]));

  const exitTexts = new Map([
    ["start", [{ text: "before the arena", toNodeId: "stormveil" }]],
    [
      "stormveil",
      [
        { text: "through the gate", toNodeId: "liurnia" },
        { text: "via the side path", toNodeId: "raya" },
      ],
    ],
  ]);

  it("attaches exit text to exits", () => {
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
    );
    const liurnia = conns.exits.find((e) => e.nodeId === "liurnia");
    expect(liurnia?.text).toBe("through the gate");
    const raya = conns.exits.find((e) => e.nodeId === "raya");
    expect(raya?.text).toBe("via the side path");
  });

  it("attaches entrance text from source node exits", () => {
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
    );
    // Entrance from start → stormveil: text is from start's exit to stormveil
    expect(conns.entrances[0].text).toBe("before the arena");
  });

  it("leaves text undefined when no exitTexts provided", () => {
    const conns = computeConnections("stormveil", EDGES, nodeMap);
    expect(conns.exits[0].text).toBeUndefined();
    expect(conns.entrances[0].text).toBeUndefined();
  });

  it("leaves text undefined for exits not in exitTexts", () => {
    const conns = computeConnections(
      "liurnia",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
    );
    // liurnia has no exit texts in the map
    const caelid = conns.exits.find((e) => e.nodeId === "caelid");
    expect(caelid?.text).toBeUndefined();
  });

  it("hides entrance text but shows exit text for undiscovered connections", () => {
    const discovered = new Set(["start", "stormveil", "liurnia"]);
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      discovered,
      exitTexts,
    );
    // liurnia is discovered → name + text visible
    const liurnia = conns.exits.find((e) => e.nodeId === "liurnia");
    expect(liurnia?.displayName).toBe("liurnia");
    expect(liurnia?.text).toBe("through the gate");
    // raya is NOT discovered → displayName hidden, but exit text still shown
    // (exit text describes the fog gate location in the current node, not the destination)
    const raya = conns.exits.find((e) => e.nodeId === "raya");
    expect(raya?.displayName).toBeNull();
    expect(raya?.text).toBe("via the side path");
    // Entrance from start → stormveil: start is discovered → text shown
    expect(conns.entrances[0].text).toBe("before the arena");
  });

  it("hides entrance text when source node is undiscovered", () => {
    // Only stormveil and caelid discovered — start is NOT (except via visibility)
    const discovered = new Set(["stormveil", "caelid"]);
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      discovered,
      exitTexts,
    );
    // Entrance from start: start is NOT in discoveredIds → text hidden
    const startEntrance = conns.entrances.find((e) => e.nodeId === "start");
    expect(startEntrance?.displayName).toBeNull();
    expect(startEntrance?.text).toBeUndefined();
  });
});

describe("parseEntranceTexts", () => {
  it("extracts entrance texts from graph.json nodes", () => {
    const graphJson = {
      nodes: {
        stormveil: {
          type: "legacy_dungeon",
          display_name: "Stormveil",
          entrances: [
            {
              text: "at the front of Margit's arena",
              from: "start",
              to: "stormveil_zone",
              to_text: "Stormveil Castle",
            },
            {
              text: "through the side gate",
              from: "liurnia",
              to: "stormveil_zone",
              to_text: "Stormveil Castle",
            },
          ],
        },
        liurnia: {
          type: "mini_dungeon",
          display_name: "Liurnia",
          entrances: [
            {
              text: "at the cave entrance",
              from: "stormveil",
              to: "liurnia_zone",
              to_text: "Liurnia",
            },
          ],
        },
        start: { type: "start", display_name: "Start" },
      },
    };
    const map = parseEntranceTexts(graphJson);
    expect(map.size).toBe(2);
    expect(map.get("stormveil")).toEqual([
      { text: "at the front of Margit's arena", fromNodeId: "start" },
      { text: "through the side gate", fromNodeId: "liurnia" },
    ]);
    expect(map.get("liurnia")).toEqual([
      { text: "at the cave entrance", fromNodeId: "stormveil" },
    ]);
    expect(map.has("start")).toBe(false);
  });

  it("returns empty map when no nodes", () => {
    expect(parseEntranceTexts({})).toEqual(new Map());
  });

  it("returns empty map when nodes have no entrances field", () => {
    const graphJson = {
      nodes: {
        start: { type: "start", display_name: "Start" },
        stormveil: {
          type: "legacy_dungeon",
          display_name: "Stormveil",
          exits: [
            { fog_id: "f1", text: "exit text", from: "z", to: "liurnia" },
          ],
        },
      },
    };
    expect(parseEntranceTexts(graphJson)).toEqual(new Map());
  });
});

describe("computeConnections with entranceTexts", () => {
  const nodeMap = new Map(NODES.map((n) => [n.id, n]));

  const exitTexts = new Map([
    ["start", [{ text: "before the arena", toNodeId: "stormveil" }]],
    [
      "stormveil",
      [
        { text: "through the gate", toNodeId: "liurnia" },
        { text: "via the side path", toNodeId: "raya" },
      ],
    ],
  ]);

  const entranceTexts = new Map([
    ["stormveil", [{ text: "at the front gate", fromNodeId: "start" }]],
    [
      "caelid",
      [
        { text: "from the swamp", fromNodeId: "liurnia" },
        { text: "past the ruins", fromNodeId: "raya" },
      ],
    ],
  ]);

  it("prefers entrance text over exit text when both available", () => {
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
      entranceTexts,
    );
    // entranceTexts has "at the front gate" for stormveil←start
    expect(conns.entrances[0].text).toBe("at the front gate");
  });

  it("falls back to exit text when no entrance text available", () => {
    // liurnia has no entranceTexts entry, so falls back to stormveil's exit text
    const conns = computeConnections(
      "liurnia",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
      entranceTexts,
    );
    expect(conns.entrances[0].text).toBe("through the gate");
  });

  it("uses entrance text for convergence node with multiple entrances", () => {
    const conns = computeConnections(
      "caelid",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
      entranceTexts,
    );
    const fromLiurnia = conns.entrances.find((e) => e.nodeId === "liurnia");
    const fromRaya = conns.entrances.find((e) => e.nodeId === "raya");
    expect(fromLiurnia?.text).toBe("from the swamp");
    expect(fromRaya?.text).toBe("past the ruins");
  });

  it("hides entrance text when source is undiscovered (anti-spoiler)", () => {
    const discovered = new Set(["stormveil", "caelid", "liurnia"]);
    const conns = computeConnections(
      "caelid",
      EDGES,
      nodeMap,
      discovered,
      exitTexts,
      entranceTexts,
    );
    // liurnia is discovered → text shown
    const fromLiurnia = conns.entrances.find((e) => e.nodeId === "liurnia");
    expect(fromLiurnia?.text).toBe("from the swamp");
    // raya is NOT discovered → text hidden
    const fromRaya = conns.entrances.find((e) => e.nodeId === "raya");
    expect(fromRaya?.text).toBeUndefined();
  });

  it("does not affect exit text logic", () => {
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      undefined,
      exitTexts,
      entranceTexts,
    );
    // Exits still use exitTexts as before
    const liurnia = conns.exits.find((e) => e.nodeId === "liurnia");
    expect(liurnia?.text).toBe("through the gate");
    const raya = conns.exits.find((e) => e.nodeId === "raya");
    expect(raya?.text).toBe("via the side path");
  });
});
