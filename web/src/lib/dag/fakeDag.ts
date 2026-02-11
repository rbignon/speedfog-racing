/**
 * Procedural fake DAG generator for blurred preview.
 * Produces a DagGraph with approximate structure based on meta-stats.
 * Uses Math.random() so the graph varies on every render, making it
 * obvious to viewers that it's not the real graph.
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

  const rand = Math.random;

  const layerSizes = distributeNodes(totalLayers, totalNodes, rand);

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

  // Create edges with richer connectivity
  const edges: DagEdge[] = [];
  const edgeSet = new Set<string>();

  const addEdge = (from: string, to: string) => {
    const key = `${from}|${to}`;
    if (!edgeSet.has(key)) {
      edges.push({ from, to });
      edgeSet.add(key);
    }
  };

  for (let layer = 0; layer < totalLayers - 1; layer++) {
    const fromIds = layerNodeIds[layer];
    const toIds = layerNodeIds[layer + 1];

    // Every source gets at least one outgoing edge (random target)
    for (const fromId of fromIds) {
      const toIdx = Math.floor(rand() * toIds.length);
      addEdge(fromId, toIds[toIdx]);
    }

    // Every target gets at least one incoming edge (random source)
    for (const toId of toIds) {
      const hasIncoming = edges.some((e) => e.to === toId);
      if (!hasIncoming) {
        const fromIdx = Math.floor(rand() * fromIds.length);
        addEdge(fromIds[fromIdx], toId);
      }
    }

    // Add cross-edges: when expanding (1→N) or contracting (N→1), add extra links
    if (fromIds.length > 1 && toIds.length > 1) {
      // Both sides have multiple nodes — add random cross-connections
      for (const fromId of fromIds) {
        for (const toId of toIds) {
          if (rand() < 0.35) addEdge(fromId, toId);
        }
      }
    } else if (fromIds.length === 1 && toIds.length > 1) {
      // Split: connect source to all targets
      for (const toId of toIds) addEdge(fromIds[0], toId);
    } else if (fromIds.length > 1 && toIds.length === 1) {
      // Merge: connect all sources to target
      for (const fromId of fromIds) addEdge(fromId, toIds[0]);
    }
  }

  return { nodes, edges, totalLayers };
}

/**
 * Distribute totalNodes across totalLayers.
 * First and last layers always get 1 node.
 * Interior layers get varied sizes with alternating expand/contract patterns.
 */
function distributeNodes(
  totalLayers: number,
  totalNodes: number,
  rand: () => number,
): number[] {
  if (totalLayers === 1) return [Math.max(1, totalNodes)];
  if (totalLayers === 2) return [1, Math.max(1, totalNodes - 1)];

  // Start with 1 per layer
  const sizes = new Array(totalLayers).fill(1);
  let remaining = totalNodes - totalLayers;

  // Assign random widths (1-3) to interior layers, favoring variation
  const interiorCount = totalLayers - 2;
  const targets: number[] = [];
  for (let i = 0; i < interiorCount; i++) {
    // Weighted: ~30% chance of 1, ~40% chance of 2, ~30% chance of 3
    const r = rand();
    targets.push(r < 0.3 ? 1 : r < 0.7 ? 2 : 3);
  }

  // Scale targets to match remaining budget
  const targetSum = targets.reduce((a, b) => a + b, 0) - interiorCount;
  if (targetSum > 0 && remaining > 0) {
    const scale = remaining / targetSum;
    for (let i = 0; i < interiorCount; i++) {
      const extra = Math.round((targets[i] - 1) * scale);
      const add = Math.min(extra, remaining, 2); // cap at +2 (3 total)
      sizes[i + 1] += add;
      remaining -= add;
    }
  }

  // Spread any leftover nodes across layers that still have room
  let idx = 1;
  let safety = interiorCount * 2;
  while (remaining > 0 && safety-- > 0) {
    if (sizes[idx] < 3) {
      sizes[idx]++;
      remaining--;
    }
    idx++;
    if (idx >= totalLayers - 1) idx = 1;
  }

  return sizes;
}
