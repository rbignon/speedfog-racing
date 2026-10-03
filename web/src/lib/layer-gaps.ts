/**
 * Layer-by-layer comparison of runners, for the gap chart and the layer
 * detail panel under the map: when each runner entered each layer, the node
 * they left it through, the time it took, the gap to the first of a
 * selection, and the whole field's reference time per node. Pure functions,
 * no DOM.
 *
 * Conventions (docs/LAYER_COMPARISON.md): a layer's arrival is the first
 * history entry on it; its node is the one the runner left it through; its
 * deaths are the ones recorded between its arrival and the next layer's.
 */

import type { ZoneHistoryEntry } from "$lib/zone-history";

export interface LayerVisit {
  /** IGT of the first history entry on a node of this layer. */
  arrivalIgt: number;
  /** First node entered on the layer. */
  firstNodeId: string;
  /** Node the runner left the layer through (the latest one while open). */
  exitNodeId: string;
  /** IGT of the first entry on the exit node within the layer's window. */
  exitEntryIgt: number;
  /** Next layer's arrival (or the finish) minus this one; null while open. */
  timeOnLayerMs: number | null;
  /** Next layer's arrival minus `exitEntryIgt`: the time spent in the node
   * the runner cleared the layer through, after any detour. */
  timeThroughNodeMs: number | null;
  /** Deaths of the entries recorded in the layer's time window. */
  deaths: number;
}

export interface RunnerTimeline {
  /** Index = layer. Null: not reached, or not placeable from the history. */
  layers: (LayerVisit | null)[];
  /** Deepest layer with a history entry, -1 for none. */
  deepestLayer: number;
  /** Final IGT, only for a finished runner. */
  finishIgt: number | null;
}

export function buildRunnerTimeline(
  history: ZoneHistoryEntry[] | null,
  nodeLayers: Map<string, number>,
  totalLayers: number,
  status: string,
  igtMs: number,
): RunnerTimeline {
  const finishIgt = status === "finished" ? igtMs : null;
  const entries: { layer: number; entry: ZoneHistoryEntry }[] = [];
  for (const entry of history ?? []) {
    const layer = nodeLayers.get(entry.node_id);
    if (layer !== undefined && layer < totalLayers) {
      entries.push({ layer, entry });
    }
  }

  const firstIdx = new Map<number, number>();
  entries.forEach(({ layer }, i) => {
    if (!firstIdx.has(layer)) firstIdx.set(layer, i);
  });

  // A layer the history can place: reached, and not first recorded after
  // the next layer.
  const placed = (layer: number): boolean => {
    const start = firstIdx.get(layer);
    if (start === undefined) return false;
    const next = firstIdx.get(layer + 1);
    return next === undefined || next > start;
  };

  const layers: (LayerVisit | null)[] = Array.from(
    { length: totalLayers },
    () => null,
  );
  let deepestLayer = -1;

  for (const [layer, start] of firstIdx) {
    deepestLayer = Math.max(deepestLayer, layer);
    if (!placed(layer)) continue;

    // The layer's window runs to the next deeper layer's first entry.
    let end = entries.length;
    for (const [other, idx] of firstIdx) {
      if (other > layer && idx > start && idx < end) end = idx;
    }

    const arrivalIgt = entries[start].entry.igt_ms;
    let exitNodeId = entries[start].entry.node_id;
    let deaths = 0;
    for (let i = start; i < end; i++) {
      if (entries[i].layer === layer) exitNodeId = entries[i].entry.node_id;
      deaths += entries[i].entry.deaths ?? 0;
    }
    let exitEntryIgt = arrivalIgt;
    for (let i = start; i < end; i++) {
      if (entries[i].entry.node_id === exitNodeId) {
        exitEntryIgt = entries[i].entry.igt_ms;
        break;
      }
    }

    let leftIgt: number | null = null;
    if (layer + 1 === totalLayers) {
      leftIgt = finishIgt;
    } else if (placed(layer + 1)) {
      leftIgt = entries[firstIdx.get(layer + 1)!].entry.igt_ms;
    }

    layers[layer] = {
      arrivalIgt,
      firstNodeId: entries[start].entry.node_id,
      exitNodeId,
      exitEntryIgt,
      timeOnLayerMs: leftIgt === null ? null : leftIgt - arrivalIgt,
      timeThroughNodeMs: leftIgt === null ? null : leftIgt - exitEntryIgt,
      deaths,
    };
  }

  return { layers, deepestLayer, finishIgt };
}

export interface TimelineRun {
  id: string;
  zone_history: ZoneHistoryEntry[] | null;
  status: string;
  igt_ms: number;
}

/** One timeline per run, keyed by participant id. */
export function buildTimelines(
  runs: TimelineRun[],
  nodeLayers: Map<string, number>,
  totalLayers: number,
): Map<string, RunnerTimeline> {
  const map = new Map<string, RunnerTimeline>();
  for (const run of runs) {
    map.set(
      run.id,
      buildRunnerTimeline(
        run.zone_history,
        nodeLayers,
        totalLayers,
        run.status,
        run.igt_ms,
      ),
    );
  }
  return map;
}

/** The timelines of the given ids, in the ids' order; unknown ids skipped. */
export function pickTimelines(
  timelines: Map<string, RunnerTimeline>,
  ids: Iterable<string>,
): Map<string, RunnerTimeline> {
  const picked = new Map<string, RunnerTimeline>();
  for (const id of ids) {
    const timeline = timelines.get(id);
    if (timeline) picked.set(id, timeline);
  }
  return picked;
}
