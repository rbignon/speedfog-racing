import { describe, it, expect } from "vitest";
import {
  computeConnections,
  computePlayersAtNode,
  computeVisitors,
  formatIgt,
  parseExitTexts,
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

  it("returns visitors sorted by arrival time", () => {
    const visitors = computeVisitors("stormveil", participants);
    expect(visitors).toHaveLength(2);
    expect(visitors[0].displayName).toBe("Alice");
    expect(visitors[0].arrivedAtMs).toBe(60000);
    expect(visitors[1].displayName).toBe("Bob");
    expect(visitors[1].arrivedAtMs).toBe(80000);
  });

  it("returns empty for unvisited node", () => {
    expect(computeVisitors("raya", [participants[0]])).toHaveLength(0);
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

  it("hides text for undiscovered connections (anti-spoiler)", () => {
    const discovered = new Set(["start", "stormveil", "liurnia"]);
    const conns = computeConnections(
      "stormveil",
      EDGES,
      nodeMap,
      discovered,
      exitTexts,
    );
    // liurnia is discovered → text visible
    const liurnia = conns.exits.find((e) => e.nodeId === "liurnia");
    expect(liurnia?.displayName).toBe("liurnia");
    expect(liurnia?.text).toBe("through the gate");
    // raya is NOT discovered → both displayName and text hidden
    const raya = conns.exits.find((e) => e.nodeId === "raya");
    expect(raya?.displayName).toBeNull();
    expect(raya?.text).toBeUndefined();
  });
});
