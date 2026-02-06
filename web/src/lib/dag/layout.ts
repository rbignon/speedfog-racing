/**
 * Pure layout algorithm for the metro DAG visualization.
 * No DOM, no Svelte — fully testable.
 */

import {
  PADDING,
  BASE_GAP,
  WEIGHT_SCALE,
  NODE_AREA,
  LAYER_SPACING_Y,
} from "./constants";
import type {
  DagGraph,
  DagLayout,
  DagNode,
  EdgeSegment,
  PositionedNode,
  RoutedEdge,
} from "./types";

// =============================================================================
// X-axis: weight-proportional horizontal spacing
// =============================================================================

/**
 * Compute the X position of each layer.
 * layerX[0] = PADDING
 * layerX[L] = layerX[L-1] + NODE_AREA + BASE_GAP + maxWeight(layer L-1) * WEIGHT_SCALE
 */
function computeLayerX(
  nodesByLayer: Map<number, DagNode[]>,
  totalLayers: number,
): number[] {
  const layerX: number[] = new Array(totalLayers).fill(0);
  layerX[0] = PADDING;

  for (let l = 1; l < totalLayers; l++) {
    const prevNodes = nodesByLayer.get(l - 1) ?? [];
    const maxWeight = prevNodes.reduce((max, n) => Math.max(max, n.weight), 1);
    layerX[l] = layerX[l - 1] + NODE_AREA + BASE_GAP + maxWeight * WEIGHT_SCALE;
  }

  return layerX;
}

// =============================================================================
// Y-axis: barycenter crossing minimization
// =============================================================================

/**
 * Group nodes by layer index.
 */
function groupByLayer(nodes: DagNode[]): Map<number, DagNode[]> {
  const map = new Map<number, DagNode[]>();
  for (const node of nodes) {
    const list = map.get(node.layer);
    if (list) {
      list.push(node);
    } else {
      map.set(node.layer, [node]);
    }
  }
  return map;
}

/**
 * Build adjacency maps for parent/child lookups.
 */
function buildAdjacency(graph: DagGraph): {
  parents: Map<string, string[]>;
  children: Map<string, string[]>;
} {
  const parents = new Map<string, string[]>();
  const children = new Map<string, string[]>();

  for (const edge of graph.edges) {
    const pList = parents.get(edge.to);
    if (pList) {
      pList.push(edge.from);
    } else {
      parents.set(edge.to, [edge.from]);
    }

    const cList = children.get(edge.from);
    if (cList) {
      cList.push(edge.to);
    } else {
      children.set(edge.from, [edge.to]);
    }
  }

  return { parents, children };
}

/**
 * Assign Y positions using 2-pass barycenter heuristic.
 * Returns a map from node ID to Y position.
 */
function computeNodeY(
  nodesByLayer: Map<number, DagNode[]>,
  parents: Map<string, string[]>,
  children: Map<string, string[]>,
): Map<string, number> {
  const yPos = new Map<string, number>();

  // Sorted layer indices
  const layers = Array.from(nodesByLayer.keys()).sort((a, b) => a - b);

  // Pass 1: left-to-right, using parents' positions
  for (const layerIdx of layers) {
    const nodes = nodesByLayer.get(layerIdx)!;

    if (layerIdx === layers[0]) {
      // First layer: center vertically
      assignEvenSpacing(nodes, yPos);
      continue;
    }

    // Compute barycenter for each node based on parents
    const barycenters: { node: DagNode; bc: number }[] = [];
    for (const node of nodes) {
      const pIds = parents.get(node.id) ?? [];
      const parentYs = pIds
        .map((id) => yPos.get(id))
        .filter((y): y is number => y !== undefined);
      const bc =
        parentYs.length > 0
          ? parentYs.reduce((s, y) => s + y, 0) / parentYs.length
          : 0;
      barycenters.push({ node, bc });
    }

    // Sort by barycenter
    barycenters.sort((a, b) => a.bc - b.bc);

    // Assign evenly-spaced Y positions centered around the mean barycenter
    const meanBc =
      barycenters.reduce((s, b) => s + b.bc, 0) / barycenters.length;
    const count = barycenters.length;
    const totalSpan = (count - 1) * LAYER_SPACING_Y;
    const startY = meanBc - totalSpan / 2;

    for (let i = 0; i < count; i++) {
      yPos.set(barycenters[i].node.id, startY + i * LAYER_SPACING_Y);
    }
  }

  // Pass 2: right-to-left, using children's positions
  for (let i = layers.length - 1; i >= 0; i--) {
    const layerIdx = layers[i];
    const nodes = nodesByLayer.get(layerIdx)!;

    if (i === layers.length - 1) {
      // Last layer already positioned, skip
      continue;
    }

    const barycenters: { node: DagNode; bc: number }[] = [];
    for (const node of nodes) {
      const cIds = children.get(node.id) ?? [];
      const childYs = cIds
        .map((id) => yPos.get(id))
        .filter((y): y is number => y !== undefined);
      if (childYs.length === 0) {
        barycenters.push({
          node,
          bc: yPos.get(node.id) ?? 0,
        });
      } else {
        const bc = childYs.reduce((s, y) => s + y, 0) / childYs.length;
        barycenters.push({ node, bc });
      }
    }

    barycenters.sort((a, b) => a.bc - b.bc);

    const meanBc =
      barycenters.reduce((s, b) => s + b.bc, 0) / barycenters.length;
    const count = barycenters.length;
    const totalSpan = (count - 1) * LAYER_SPACING_Y;
    const startY = meanBc - totalSpan / 2;

    for (let j = 0; j < count; j++) {
      yPos.set(barycenters[j].node.id, startY + j * LAYER_SPACING_Y);
    }
  }

  return yPos;
}

/**
 * Assign evenly-spaced Y positions centered around 0.
 */
function assignEvenSpacing(nodes: DagNode[], yPos: Map<string, number>): void {
  const count = nodes.length;
  const totalSpan = (count - 1) * LAYER_SPACING_Y;
  const startY = -totalSpan / 2;
  for (let i = 0; i < count; i++) {
    yPos.set(nodes[i].id, startY + i * LAYER_SPACING_Y);
  }
}

// =============================================================================
// Edge routing: horizontal + 45-degree diagonal (metro convention)
// =============================================================================

/**
 * Route an edge from (x1,y1) to (x2,y2) using metro-style segments.
 * - If dy == 0: single horizontal segment
 * - Else: 3 segments — horizontal departure, 45-degree diagonal, horizontal arrival
 */
function routeEdge(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): EdgeSegment[] {
  const dy = y2 - y1;

  if (Math.abs(dy) < 0.5) {
    // Horizontal: single segment
    return [{ x1, y1, x2, y2: y1 }];
  }

  // 3-segment metro routing
  const totalDx = x2 - x1;
  const absDy = Math.abs(dy);
  const diagDx = absDy; // 45-degree: horizontal distance = vertical distance

  // Prefer starting the diagonal at 35% of horizontal span
  let diagStartX = x1 + totalDx * 0.35;

  // If the diagonal would overshoot x2, pull the start back so it fits
  if (diagStartX + diagDx > x2) {
    diagStartX = Math.max(x1, x2 - diagDx);
  }

  const diagEndX = diagStartX + diagDx;

  return [
    // Horizontal departure
    { x1, y1, x2: diagStartX, y2: y1 },
    // 45-degree diagonal (always covers the full vertical distance)
    { x1: diagStartX, y1, x2: diagEndX, y2 },
    // Horizontal arrival
    { x1: diagEndX, y1: y2, x2, y2 },
  ];
}

// =============================================================================
// Main layout function
// =============================================================================

/**
 * Compute the full metro DAG layout.
 * Pure function — no DOM, no side effects.
 */
export function computeLayout(graph: DagGraph): DagLayout {
  if (graph.nodes.length === 0) {
    return { nodes: [], edges: [], width: 0, height: 0 };
  }

  const nodesByLayer = groupByLayer(graph.nodes);
  const { parents, children } = buildAdjacency(graph);

  // Compute X positions per layer
  const layerX = computeLayerX(nodesByLayer, graph.totalLayers);

  // Compute Y positions via barycenter heuristic
  const yPos = computeNodeY(nodesByLayer, parents, children);

  // Build positioned nodes
  const nodeMap = new Map<string, PositionedNode>();
  const positionedNodes: PositionedNode[] = graph.nodes.map((node) => {
    const pn: PositionedNode = {
      ...node,
      x: layerX[node.layer] ?? PADDING,
      y: yPos.get(node.id) ?? 0,
    };
    nodeMap.set(node.id, pn);
    return pn;
  });

  // Route edges
  const routedEdges: RoutedEdge[] = graph.edges.map((edge) => {
    const from = nodeMap.get(edge.from)!;
    const to = nodeMap.get(edge.to)!;
    return {
      fromId: edge.from,
      toId: edge.to,
      segments: routeEdge(from.x, from.y, to.x, to.y),
    };
  });

  // Compute bounding box and normalize Y so all values are positive
  const allY = positionedNodes.map((n) => n.y);
  const minY = Math.min(...allY);
  const maxY = Math.max(...allY);
  const yOffset = PADDING - minY;

  // Shift all Y positions
  for (const node of positionedNodes) {
    node.y += yOffset;
  }
  for (const edge of routedEdges) {
    for (const seg of edge.segments) {
      seg.y1 += yOffset;
      seg.y2 += yOffset;
    }
  }

  // Final dimensions
  const maxX = Math.max(...positionedNodes.map((n) => n.x));
  const width = maxX + PADDING;
  const height = maxY - minY + PADDING * 2;

  return {
    nodes: positionedNodes,
    edges: routedEdges,
    width,
    height,
  };
}
