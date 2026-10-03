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
import { isOutOfRace } from "$lib/format";
import { BASE_GAP, NODE_AREA } from "$lib/dag/constants";

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

/** Arrival IGT at a layer; `index === layers.length` is the finish. */
export function arrivalAt(t: RunnerTimeline, index: number): number | null {
  if (index === t.layers.length) return t.finishIgt;
  return t.layers[index]?.arrivalIgt ?? null;
}

/**
 * Each runner's gap to the first of the selection to enter each layer,
 * indexed 0..totalLayers (the last index is the finish). Null where the
 * runner has no arrival; the first in, ties included, gets 0.
 */
export function selectionGaps(
  timelines: Map<string, RunnerTimeline>,
  totalLayers: number,
): Map<string, (number | null)[]> {
  const gaps = new Map<string, (number | null)[]>();
  for (const id of timelines.keys()) gaps.set(id, []);
  for (let index = 0; index <= totalLayers; index++) {
    let first = Infinity;
    for (const t of timelines.values()) {
      const arrival = arrivalAt(t, index);
      if (arrival !== null && arrival < first) first = arrival;
    }
    for (const [id, t] of timelines) {
      const arrival = arrivalAt(t, index);
      gaps.get(id)!.push(arrival === null ? null : arrival - first);
    }
  }
  return gaps;
}

export interface GapSeries {
  /** Gap at each layer entry (index totalLayers: the finish); a layer the
   * runner has no arrival on is skipped, so the line joins its neighbours. */
  points: { index: number; gapMs: number }[];
  /** Deaths on a finished layer, drawn on its segment: `midGapMs` is the
   * segment's middle height. An open layer has no segment, so no mark. */
  deathMarks: { layer: number; count: number; midGapMs: number }[];
  /** The runner is out of the race: the line ends on a terminus. */
  terminus: boolean;
}

export function gapSeries(
  timeline: RunnerTimeline,
  gaps: (number | null)[],
  status: string,
): GapSeries {
  const points: GapSeries["points"] = [];
  gaps.forEach((gapMs, index) => {
    if (gapMs !== null) points.push({ index, gapMs });
  });
  const deathMarks: GapSeries["deathMarks"] = [];
  timeline.layers.forEach((visit, layer) => {
    const from = gaps[layer];
    const to = gaps[layer + 1];
    if (
      visit &&
      visit.deaths > 0 &&
      visit.timeOnLayerMs !== null &&
      from != null &&
      to != null
    ) {
      deathMarks.push({
        layer,
        count: visit.deaths,
        midGapMs: (from + to) / 2,
      });
    }
  });
  return { points, deathMarks, terminus: isOutOfRace(status) };
}

export interface NodeFieldStats {
  bestMs: number;
  medianMs: number;
  count: number;
  /** Every runner's time through the node, ascending. */
  samples: number[];
}

/**
 * The field's reference per node: the time through the node of every runner
 * who left a layer through it. A disqualified run never sets the reference.
 */
export function computeFieldStats(
  runs: Iterable<{ status: string; timeline: RunnerTimeline }>,
): Map<string, NodeFieldStats> {
  const byNode = new Map<string, number[]>();
  for (const { status, timeline } of runs) {
    if (status === "disqualified") continue;
    for (const visit of timeline.layers) {
      if (!visit || visit.timeThroughNodeMs === null) continue;
      const samples = byNode.get(visit.exitNodeId);
      if (samples) samples.push(visit.timeThroughNodeMs);
      else byNode.set(visit.exitNodeId, [visit.timeThroughNodeMs]);
    }
  }
  const stats = new Map<string, NodeFieldStats>();
  for (const [nodeId, samples] of byNode) {
    samples.sort((a, b) => a - b);
    const mid = Math.floor(samples.length / 2);
    const medianMs =
      samples.length % 2 === 1
        ? samples[mid]
        : (samples[mid - 1] + samples[mid]) / 2;
    stats.set(nodeId, {
      bestMs: samples[0],
      medianMs,
      count: samples.length,
      samples,
    });
  }
  return stats;
}

/** 1 + the number of strictly faster samples: ties share a rank. */
export function fieldRank(stats: NodeFieldStats, ms: number): number {
  let faster = 0;
  for (const sample of stats.samples) {
    if (sample >= ms) break;
    faster++;
  }
  return faster + 1;
}

/**
 * done: the runner left the layer; live: still on it (playing); out: left
 * the race on it; unknown: left it, but the history missed when.
 */
export type DetailState = "done" | "live" | "out" | "unknown";

export interface DetailRow {
  id: string;
  state: DetailState;
  entryGapMs: number | null;
  /** done: time on the layer; live: time so far; otherwise null. */
  timeMs: number | null;
  /** done only: time on the layer minus the selection's shortest. */
  vsBestMs: number | null;
  /** done only: rank of the time through the node among the field. */
  fieldRank: number | null;
  deaths: number;
  /** The node first entered, when the runner left through another one. */
  backedOutOf: string | null;
  detourMs: number | null;
}

export interface DetailColumn {
  nodeId: string;
  field: NodeFieldStats | null;
  rows: DetailRow[];
}

export interface DetailRunner {
  id: string;
  status: string;
  /** Live IGT, for a playing runner's time so far. */
  igtMs: number;
  timeline: RunnerTimeline;
}

const STATE_ORDER: Record<DetailState, number> = {
  done: 0,
  live: 1,
  unknown: 2,
  out: 3,
};

function fastestDone(column: DetailColumn): number {
  let best = Infinity;
  for (const row of column.rows) {
    if (row.state === "done" && row.timeMs !== null && row.timeMs < best) {
      best = row.timeMs;
    }
  }
  return best;
}

/**
 * The layer detail: one column per node the runners left the layer
 * through, the fastest node first, each runner's row in it.
 */
export function buildLayerDetail(
  layer: number,
  runners: DetailRunner[],
  gaps: Map<string, (number | null)[]>,
  field: Map<string, NodeFieldStats>,
): DetailColumn[] {
  const rows: { nodeId: string; row: DetailRow }[] = [];
  for (const { id, status, igtMs, timeline } of runners) {
    const visit = timeline.layers[layer];
    if (!visit) continue;

    let state: DetailState;
    let timeMs: number | null = null;
    if (visit.timeOnLayerMs !== null) {
      state = "done";
      timeMs = visit.timeOnLayerMs;
    } else if (layer === timeline.deepestLayer) {
      if (status === "playing") {
        state = "live";
        timeMs = Math.max(0, igtMs - visit.arrivalIgt);
      } else {
        state = "out";
      }
    } else {
      state = "unknown";
    }

    const stats = field.get(visit.exitNodeId);
    const backedOut = visit.exitNodeId !== visit.firstNodeId;
    rows.push({
      nodeId: visit.exitNodeId,
      row: {
        id,
        state,
        entryGapMs: gaps.get(id)?.[layer] ?? null,
        timeMs,
        vsBestMs: null,
        fieldRank:
          state === "done" && stats && visit.timeThroughNodeMs !== null
            ? fieldRank(stats, visit.timeThroughNodeMs)
            : null,
        deaths: visit.deaths,
        backedOutOf: backedOut ? visit.firstNodeId : null,
        detourMs: backedOut ? visit.exitEntryIgt - visit.arrivalIgt : null,
      },
    });
  }

  let best = Infinity;
  for (const { row } of rows) {
    if (row.state === "done" && row.timeMs !== null && row.timeMs < best) {
      best = row.timeMs;
    }
  }

  const columns = new Map<string, DetailColumn>();
  for (const { nodeId, row } of rows) {
    if (row.state === "done" && row.timeMs !== null) {
      row.vsBestMs = row.timeMs - best;
    }
    let column = columns.get(nodeId);
    if (!column) {
      column = { nodeId, field: field.get(nodeId) ?? null, rows: [] };
      columns.set(nodeId, column);
    }
    column.rows.push(row);
  }

  const result = [...columns.values()];
  for (const column of result) {
    column.rows.sort(
      (a, b) =>
        STATE_ORDER[a.state] - STATE_ORDER[b.state] ||
        (a.timeMs ?? 0) - (b.timeMs ?? 0) ||
        a.id.localeCompare(b.id),
    );
  }
  result.sort((a, b) => {
    const fa = fastestDone(a);
    const fb = fastestDone(b);
    if (fa !== fb) return fa < fb ? -1 : 1;
    return a.nodeId.localeCompare(b.nodeId);
  });
  return result;
}

/** Each layer's column x, read off the positioned map nodes (all the nodes
 * of a layer share it). */
export function layerColumnXs(
  nodes: { layer: number; x: number }[],
  totalLayers: number,
): number[] {
  const xs = new Array<number>(totalLayers).fill(0);
  for (const node of nodes) {
    if (node.layer < totalLayers) xs[node.layer] = node.x;
  }
  return xs;
}

/** Distance between two layer columns when there is only one to measure. */
const DEFAULT_COLUMN_SPACING = BASE_GAP + NODE_AREA;

/**
 * Where each layer is entered, on the fog gate halfway between its column
 * and the previous one: gate L is layer L's entry, the last gate is the
 * finish, half a spacing past the last column. The chart segment between
 * two gates sits right under the layer's nodes.
 */
export function gateXs(layerXs: number[]): number[] {
  const n = layerXs.length;
  if (n === 0) return [];
  const firstHalf =
    (n > 1 ? layerXs[1] - layerXs[0] : DEFAULT_COLUMN_SPACING) / 2;
  const lastHalf =
    (n > 1 ? layerXs[n - 1] - layerXs[n - 2] : DEFAULT_COLUMN_SPACING) / 2;
  const gates = [layerXs[0] - firstHalf];
  for (let i = 1; i < n; i++) gates.push((layerXs[i - 1] + layerXs[i]) / 2);
  gates.push(layerXs[n - 1] + lastHalf);
  return gates;
}

/** The layer whose column holds x (between its gate and the next one). */
export function layerAtX(x: number, gates: number[]): number | null {
  for (let layer = 0; layer < gates.length - 1; layer++) {
    if (x >= gates[layer] && x < gates[layer + 1]) return layer;
  }
  return null;
}

const TICK_STEPS_MS = [1, 2, 5, 10, 20, 30, 60].map((m) => m * 60_000);
const MAX_TICK_INTERVALS = 5;

/** The y axis: the smallest step keeping at most five intervals, the top
 * rounded up to it, one step minimum. */
export function gapTicks(maxGapMs: number): { stepMs: number; topMs: number } {
  const stepMs =
    TICK_STEPS_MS.find((s) => Math.ceil(maxGapMs / s) <= MAX_TICK_INTERVALS) ??
    TICK_STEPS_MS[TICK_STEPS_MS.length - 1];
  return {
    stepMs,
    topMs: Math.max(stepMs, Math.ceil(maxGapMs / stepMs) * stepMs),
  };
}

/** Moves a pinned layer one column, starting from an end when none is. */
export function stepLayer(
  current: number | null,
  delta: 1 | -1,
  totalLayers: number,
): number {
  if (current === null) return delta > 0 ? 0 : totalLayers - 1;
  return Math.min(totalLayers - 1, Math.max(0, current + delta));
}
