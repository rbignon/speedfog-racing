/**
 * DAG type definitions and graph parser for metro-style visualization.
 */

// =============================================================================
// Input types (parsed from graph.json v3)
// =============================================================================

export type DagNodeType =
  | "start"
  | "mini_dungeon"
  | "boss_arena"
  | "major_boss"
  | "legacy_dungeon"
  | "final_boss";

export interface DagNode {
  id: string;
  type: DagNodeType;
  displayType?: string; // Translated type label from server (e.g. "donjon majeur")
  displayName: string;
  /** The name the map labels, leaderboards and cast scenes show: the display
   * name, except that a boss arena's last leg (the arena's own boss) gives
   * way to the boss actually fought there. The node popup keeps displayName,
   * next to its own boss line. */
  labelName: string;
  zones: string[];
  layer: number;
  tier: number;
  weight: number;
  randomizedBosses?: string[]; // Boss names when boss randomization is active (one per phase)
}

export interface DagEdge {
  from: string;
  to: string;
}

export interface DagGraph {
  nodes: DagNode[];
  edges: DagEdge[];
  totalLayers: number;
}

// =============================================================================
// Output types (layout results)
// =============================================================================

export interface PositionedNode extends DagNode {
  x: number;
  y: number;
}

export interface EdgeSegment {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface RoutedEdge {
  fromId: string;
  toId: string;
  segments: EdgeSegment[];
}

export interface DagLayout {
  nodes: PositionedNode[];
  edges: RoutedEdge[];
  width: number;
  height: number;
  /** Each layer's column x, indexed by layer. */
  layerX: number[];
}

// =============================================================================
// Parser
// =============================================================================

const VALID_NODE_TYPES = new Set<string>([
  "start",
  "mini_dungeon",
  "boss_arena",
  "major_boss",
  "legacy_dungeon",
  "final_boss",
]);

/**
 * A boss arena's display name ends with the arena's own boss ("Caelid - Gael
 * Tunnel - Magma Wyrm"): when the seed randomizes it, swap that last leg for
 * the boss(es) actually fought there. A boss arena left alone keeps its
 * name, which already names its boss: its boss_name is no fallback, since
 * older seeds carry the generator's raw names there ("Magma Wyrm Boss"),
 * with no translation either. Boss names never contain " - ", so the label
 * still splits into the same legs.
 */
function bossArenaLabel(
  displayName: string,
  randomizedBosses: string[] | undefined,
): string {
  const bosses = (randomizedBosses ?? []).filter(
    (b) => typeof b === "string" && b,
  );
  if (bosses.length === 0) return displayName;
  const boss = bosses.join(", ");
  const cut = displayName.lastIndexOf(" - ");
  return cut === -1 ? boss : displayName.slice(0, cut + 3) + boss;
}

/**
 * Parse raw graph.json (v3) server data into typed DagGraph.
 */
export function parseDagGraph(graphJson: Record<string, unknown>): DagGraph {
  const rawNodes = graphJson.nodes as Record<string, Record<string, unknown>>;
  const rawEdges = graphJson.edges as Array<Record<string, string>>;
  const totalLayers = (graphJson.total_layers as number) ?? 0;

  const nodes: DagNode[] = [];
  for (const [id, raw] of Object.entries(rawNodes)) {
    const nodeType = raw.type as string;
    if (!VALID_NODE_TYPES.has(nodeType)) {
      continue;
    }
    const displayName = (raw.display_name as string) ?? id;
    const randomizedBosses = Array.isArray(raw.randomized_bosses)
      ? (raw.randomized_bosses as string[])
      : undefined;
    nodes.push({
      id,
      type: nodeType as DagNodeType,
      displayType: (raw.display_type as string) ?? undefined,
      displayName,
      labelName:
        nodeType === "boss_arena"
          ? bossArenaLabel(displayName, randomizedBosses)
          : displayName,
      zones: (raw.zones as string[]) ?? [],
      layer: (raw.layer as number) ?? 0,
      tier: (raw.tier as number) ?? 0,
      weight: (raw.weight as number) ?? 1,
      randomizedBosses,
    });
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges: DagEdge[] = (rawEdges ?? [])
    .filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to))
    .map((e) => ({ from: e.from, to: e.to }));

  return { nodes, edges, totalLayers };
}
