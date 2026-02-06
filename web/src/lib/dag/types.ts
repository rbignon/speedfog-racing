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
  displayName: string;
  zones: string[];
  layer: number;
  tier: number;
  weight: number;
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
    nodes.push({
      id,
      type: nodeType as DagNodeType,
      displayName: (raw.display_name as string) ?? id,
      zones: (raw.zones as string[]) ?? [],
      layer: (raw.layer as number) ?? 0,
      tier: (raw.tier as number) ?? 0,
      weight: (raw.weight as number) ?? 1,
    });
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges: DagEdge[] = (rawEdges ?? [])
    .filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to))
    .map((e) => ({ from: e.from, to: e.to }));

  return { nodes, edges, totalLayers };
}
