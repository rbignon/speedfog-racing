/**
 * LiveSplit splits files (.lss) for SpeedFog runs: one segment per graph
 * layer, a "Personal Best" and a "SpeedFog WR" comparison in Game Time, and
 * a custom variable naming the seed (seed file) or the category (category
 * file) the file belongs to, which the mod reads to check the file matches
 * the run. Pure functions apart from `downloadLss`; see docs/LIVESPLIT.md.
 *
 * Segment k ends on the first arrival on layer k+1, the last one on the
 * finish, as `buildRunnerTimeline` places them.
 */

import type { SpeedrunSeed, SpeedrunSeedRun } from "$lib/api";
import { parseDagGraph } from "$lib/dag";
import { parseNodeLayers } from "$lib/dag/popupData";
import { buildRunnerTimeline, type RunnerTimeline } from "$lib/layer-gaps";

/** Never "Elden Ring": LiveSplit would wake the SoulSplitter autosplitter. */
const GAME_NAME = "SpeedFog";
const PB_COMPARISON = "Personal Best";
const WR_COMPARISON = "SpeedFog WR";
const SEED_VARIABLE = "SpeedFog seed";
const CATEGORY_VARIABLE = "SpeedFog category";

/** Cumulative split time per segment (ms, null when unknown): index k is the
 * arrival on layer k+1, the last one the finish. */
export type SplitTimes = (number | null)[];

export interface LssFile {
  /** LiveSplit's CategoryName. */
  categoryName: string;
  /** "SpeedFog seed" variable (seed file). */
  seedNumber: string | null;
  /** "SpeedFog category" variable (category file). */
  categoryKey: string | null;
  /** Length = total layers. */
  segmentNames: string[];
  pb: SplitTimes | null;
  wr: SplitTimes | null;
  golds: (number | null)[] | null;
}

export function splitTimesFromTimeline(
  t: RunnerTimeline,
  totalLayers: number,
): SplitTimes {
  return Array.from({ length: totalLayers }, (_, k) =>
    k + 1 < totalLayers ? (t.layers[k + 1]?.arrivalIgt ?? null) : t.finishIgt,
  );
}

/** Split times from a category endpoint's `layer_entry_igts`: first arrival
 * per layer from "0", the finish under the key `totalLayers`. */
export function splitTimesFromEntries(
  entries: Record<string, number>,
  totalLayers: number,
): SplitTimes {
  return Array.from({ length: totalLayers }, (_, k) => {
    const v = entries[String(k + 1)];
    return typeof v === "number" ? v : null;
  });
}

/** Time spent in each segment; unknown around a gap or when the clock went
 * back. */
export function segmentTimes(splits: SplitTimes): (number | null)[] {
  return splits.map((t, k) => {
    const prev = k === 0 ? 0 : splits[k - 1];
    if (t === null || prev === null || t < prev) return null;
    return t - prev;
  });
}

function fastest(runs: SpeedrunSeedRun[]): SpeedrunSeedRun | null {
  let best: SpeedrunSeedRun | null = null;
  for (const r of runs) {
    if (
      best === null ||
      r.igt_ms < best.igt_ms ||
      (r.igt_ms === best.igt_ms && r.finished_at < best.finished_at)
    ) {
      best = r;
    }
  }
  return best;
}

/** The seed file of a played seed, null while its graph is not public. */
export function seedLssFile(
  seed: SpeedrunSeed,
  viewerId: string | null,
): LssFile | null {
  if (!seed.graph_json) return null;
  const total = seed.total_layers;
  const nodeLayers = parseNodeLayers(seed.graph_json);
  const labels = new Map(
    parseDagGraph(seed.graph_json).nodes.map((n) => [n.id, n.labelName]),
  );
  const timeline = (r: SpeedrunSeedRun) =>
    buildRunnerTimeline(
      r.zone_history,
      nodeLayers,
      total,
      "finished",
      r.igt_ms,
    );

  const wrRun = fastest(seed.runs.filter((r) => r.ranked));
  const mine =
    viewerId === null ? [] : seed.runs.filter((r) => r.user.id === viewerId);
  const pbRun = fastest(mine);
  const wrTimeline = wrRun ? timeline(wrRun) : null;
  const pbTimeline = pbRun ? timeline(pbRun) : null;

  const exitName = (t: RunnerTimeline | null, k: number): string | null => {
    const id = t?.layers[k]?.exitNodeId;
    return id === undefined ? null : (labels.get(id) ?? null);
  };
  const segmentNames = Array.from(
    { length: total },
    (_, k) =>
      exitName(pbTimeline, k) ?? exitName(wrTimeline, k) ?? `Depth ${k + 1}`,
  );

  // Segments as LiveSplit times them: the first one from IGT 0, not from
  // the run's first history entry.
  let golds: (number | null)[] | null = null;
  if (mine.length > 0) {
    const g: (number | null)[] = Array.from({ length: total }, () => null);
    for (const r of mine) {
      segmentTimes(splitTimesFromTimeline(timeline(r), total)).forEach(
        (t, k) => {
          if (t !== null && (g[k] === null || t < g[k]!)) g[k] = t;
        },
      );
    }
    golds = g;
  }

  return {
    categoryName: `${seed.category_name} · Seed ${seed.seed_number}`,
    seedNumber: seed.seed_number,
    categoryKey: null,
    segmentNames,
    pb: pbTimeline && splitTimesFromTimeline(pbTimeline, total),
    wr: wrTimeline && splitTimesFromTimeline(wrTimeline, total),
    golds,
  };
}

/** The category file: Depth names, comparisons from the board's per-layer
 * arrival IGTs (null for a category without a board or a viewer without a
 * PB), golds from the PB's own segments. */
export function categoryLssFile(
  categoryKey: string,
  categoryName: string,
  totalLayers: number,
  wr: Record<string, number> | null,
  pb: Record<string, number> | null,
): LssFile {
  const pbSplits = pb && splitTimesFromEntries(pb, totalLayers);
  return {
    categoryName,
    seedNumber: null,
    categoryKey,
    segmentNames: Array.from(
      { length: totalLayers },
      (_, k) => `Depth ${k + 1}`,
    ),
    pb: pbSplits,
    wr: wr && splitTimesFromEntries(wr, totalLayers),
    golds: pbSplits && segmentTimes(pbSplits),
  };
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

/** LiveSplit's `HH:MM:SS.fffffff`, from milliseconds. */
function formatLssTime(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const h = Math.floor(total / 3_600_000);
  const m = Math.floor((total % 3_600_000) / 60_000);
  const s = Math.floor((total % 60_000) / 1000);
  const pad = (n: number, w: number) => String(n).padStart(w, "0");
  return `${pad(h, 2)}:${pad(m, 2)}:${pad(s, 2)}.${pad(total % 1000, 3)}0000`;
}

function gameTime(ms: number | null | undefined): string {
  return ms == null ? "" : `<GameTime>${formatLssTime(ms)}</GameTime>`;
}

export function buildLss(file: LssFile): string {
  const variables: string[] = [];
  if (file.seedNumber !== null) {
    variables.push(
      `<Variable name="${SEED_VARIABLE}">${escapeXml(file.seedNumber)}</Variable>`,
    );
  }
  if (file.categoryKey !== null) {
    variables.push(
      `<Variable name="${CATEGORY_VARIABLE}">${escapeXml(file.categoryKey)}</Variable>`,
    );
  }
  const segments = file.segmentNames.map(
    (name, k) =>
      `<Segment><Name>${escapeXml(name)}</Name><Icon></Icon><SplitTimes>` +
      `<SplitTime name="${PB_COMPARISON}">${gameTime(file.pb?.[k])}</SplitTime>` +
      `<SplitTime name="${WR_COMPARISON}">${gameTime(file.wr?.[k])}</SplitTime>` +
      `</SplitTimes><BestSegmentTime>${gameTime(file.golds?.[k])}</BestSegmentTime>` +
      `<SegmentHistory /></Segment>`,
  );
  return (
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<Run version="1.7.0"><GameIcon /><GameName>${GAME_NAME}</GameName>` +
    `<CategoryName>${escapeXml(file.categoryName)}</CategoryName>` +
    `<LayoutPath></LayoutPath><Metadata><Run id="" />` +
    `<Platform usesEmulator="False"></Platform><Region></Region><Variables />` +
    `<CustomVariables>${variables.join("")}</CustomVariables></Metadata>` +
    `<Offset>00:00:00</Offset><AttemptCount>0</AttemptCount>` +
    `<AttemptHistory /><Segments>${segments.join("")}</Segments>` +
    `<AutoSplitterSettings /></Run>\n`
  );
}

/** `SpeedFog - <Category> - Seed <n>.lss` or `SpeedFog - <Category>.lss`,
 * with the characters a file name cannot hold turned into spaces. */
export function lssFileName(file: LssFile): string {
  const category = (
    file.seedNumber === null
      ? file.categoryName
      : file.categoryName.replace(/ · Seed .*$/, "")
  )
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return file.seedNumber === null
    ? `${GAME_NAME} - ${category}.lss`
    : `${GAME_NAME} - ${category} - Seed ${file.seedNumber}.lss`;
}

/** Save the splits file in the browser. */
export function downloadLss(file: LssFile): void {
  const blob = new Blob([buildLss(file)], { type: "application/xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = lssFileName(file);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
