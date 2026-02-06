/**
 * Procedural fake DAG generator for blurred preview.
 * Produces a DagGraph with approximate structure based on meta-stats.
 */

import type { DagGraph, DagNode, DagEdge } from "./types";

/**
 * Generate a fake DAG with the given meta-stats.
 * The graph has roughly `totalNodes` nodes distributed across `totalLayers`,
 * with edges creating splits/merges to approximate `totalPaths`.
 */
export function generateFakeDag(
  totalLayers: number,
  totalNodes: number,
  totalPaths: number,
): DagGraph {
  if (totalLayers <= 0 || totalNodes <= 0) {
    return { nodes: [], edges: [], totalLayers: 0 };
  }

  // Distribute nodes across layers (first and last get 1 each)
  const layerSizes = distributeNodes(totalLayers, totalNodes);

  // Create nodes
  const nodes: DagNode[] = [];
  const layerNodeIds: string[][] = [];

  for (let layer = 0; layer < totalLayers; layer++) {
    const ids: string[] = [];
    const count = layerSizes[layer];
    for (let i = 0; i < count; i++) {
      const id = `fake_${layer}_${i}`;
      ids.push(id);
      let type: DagNode["type"] = "mini_dungeon";
      if (layer === 0) type = "start";
      else if (layer === totalLayers - 1) type = "final_boss";
      else if (count === 1 && layer > totalLayers / 2) type = "boss_arena";

      nodes.push({
        id,
        type,
        displayName: id,
        zones: [id],
        layer,
        tier: layer,
        weight: 1,
      });
    }
    layerNodeIds.push(ids);
  }

  // Create edges: connect every node in layer L to at least one in layer L+1
  const edges: DagEdge[] = [];

  for (let layer = 0; layer < totalLayers - 1; layer++) {
    const fromIds = layerNodeIds[layer];
    const toIds = layerNodeIds[layer + 1];

    // Every source must have at least one outgoing edge
    for (const fromId of fromIds) {
      const toIdx = edges.length % toIds.length;
      edges.push({ from: fromId, to: toIds[toIdx] });
    }

    // Every target must have at least one incoming edge
    const coveredTargets = new Set(
      edges.filter((e) => toIds.includes(e.to)).map((e) => e.to),
    );
    for (const toId of toIds) {
      if (!coveredTargets.has(toId)) {
        const fromIdx = 0;
        edges.push({ from: fromIds[fromIdx], to: toId });
      }
    }
  }

  // Add extra edges to approximate totalPaths (create splits/merges)
  const desiredExtraEdges = Math.max(0, totalPaths - 1);
  let added = 0;
  const edgeSet = new Set(edges.map((e) => `${e.from}|${e.to}`));

  for (
    let layer = 0;
    layer < totalLayers - 1 && added < desiredExtraEdges;
    layer++
  ) {
    const fromIds = layerNodeIds[layer];
    const toIds = layerNodeIds[layer + 1];
    if (fromIds.length === 1 && toIds.length === 1) continue;

    for (const fromId of fromIds) {
      for (const toId of toIds) {
        const key = `${fromId}|${toId}`;
        if (!edgeSet.has(key) && added < desiredExtraEdges) {
          edges.push({ from: fromId, to: toId });
          edgeSet.add(key);
          added++;
        }
      }
    }
  }

  return { nodes, edges, totalLayers };
}

/**
 * Distribute totalNodes across totalLayers.
 * First and last layers always get 1 node.
 * Interior layers get 1-3 nodes to create splits/merges.
 */
function distributeNodes(totalLayers: number, totalNodes: number): number[] {
  if (totalLayers === 1) return [Math.max(1, totalNodes)];
  if (totalLayers === 2) return [1, Math.max(1, totalNodes - 1)];

  const sizes = new Array(totalLayers).fill(1);
  let remaining = totalNodes - totalLayers;

  // Distribute remaining nodes to interior layers (not first/last)
  let idx = 1;
  while (remaining > 0 && idx < totalLayers - 1) {
    const add = Math.min(remaining, 2); // cap at 3 per layer
    sizes[idx] += add;
    remaining -= add;
    idx++;
    if (idx >= totalLayers - 1) idx = 1;
  }

  return sizes;
}
