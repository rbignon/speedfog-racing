/**
 * speedrun.fog History chart: axis ticks and pointer snapping. Pure,
 * unit-tested; the drawing lives in SpeedrunHistoryChart.svelte.
 */

const SECOND_MS = 1000;
const DAY_MS = 86_400_000;
const MAX_INTERVALS = 5;
const MAX_DATE_TICKS = 6;
// Spans under this many days get day ticks, longer ones month ticks.
const DAY_MODE_MAX_DAYS = 60;

const TIME_STEPS_S = [
  1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200,
];
const DAY_STEPS = [1, 2, 3, 5, 7, 14];
const MONTH_STEPS = [1, 2, 3, 6, 12];

export interface TimeAxis {
  /** Axis bounds, on round values around the data. */
  min: number;
  max: number;
  ticks: number[];
}

/** Y axis for times (ms): the smallest round step whose bounds around the
 * data keep at most five intervals. A single value gets 30s of air on both
 * sides so it sits inside the axis. */
export function timeTicks(minMs: number, maxMs: number): TimeAxis {
  const lo = maxMs - minMs < SECOND_MS ? minMs - 30 * SECOND_MS : minMs;
  const hi = maxMs - minMs < SECOND_MS ? maxMs + 30 * SECOND_MS : maxMs;
  // Times span minutes to a few hours; past ten hours the last step simply
  // yields more ticks.
  for (const [i, stepS] of TIME_STEPS_S.entries()) {
    const step = stepS * SECOND_MS;
    const first = Math.floor(lo / step);
    const last = Math.ceil(hi / step);
    if (last - first <= MAX_INTERVALS || i === TIME_STEPS_S.length - 1) {
      const ticks: number[] = [];
      for (let t = first; t <= last; t++) ticks.push(t * step);
      return { min: first * step, max: last * step, ticks };
    }
  }
  throw new Error("unreachable: TIME_STEPS_S is not empty");
}

export interface DateTick {
  time: number;
  label: string;
}

/** The viewer's calendar day as a day count since the epoch. */
function dayNumber(d: Date): number {
  return Math.round(
    Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY_MS,
  );
}

function dayTicks(
  startMs: number,
  endMs: number,
  maxTicks: number,
): DateTick[] {
  let ticks: DateTick[] = [];
  for (const step of DAY_STEPS) {
    ticks = [];
    const start = new Date(startMs);
    const day = new Date(
      start.getFullYear(),
      start.getMonth(),
      start.getDate(),
    );
    for (; day.getTime() <= endMs; day.setDate(day.getDate() + 1)) {
      if (day.getTime() < startMs || dayNumber(day) % step !== 0) continue;
      ticks.push({
        time: day.getTime(),
        label: day.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
      });
    }
    if (ticks.length <= maxTicks) return ticks;
  }
  // No step fits the budget (a span of years): the coarsest step still
  // labels the axis.
  return ticks;
}

function monthTicks(
  startMs: number,
  endMs: number,
  maxTicks: number,
): DateTick[] {
  let ticks: DateTick[] = [];
  for (const step of MONTH_STEPS) {
    ticks = [];
    const start = new Date(startMs);
    const month = new Date(start.getFullYear(), start.getMonth(), 1);
    for (; month.getTime() <= endMs; month.setMonth(month.getMonth() + 1)) {
      const index = month.getFullYear() * 12 + month.getMonth();
      if (month.getTime() < startMs || index % step !== 0) continue;
      const name = month.toLocaleDateString("en-US", { month: "short" });
      ticks.push({
        time: month.getTime(),
        label: month.getMonth() === 0 ? `${name} ${month.getFullYear()}` : name,
      });
    }
    if (ticks.length <= maxTicks) return ticks;
  }
  // No step fits the budget (a span of years): the coarsest step still
  // labels the axis.
  return ticks;
}

/** X axis for dates: month starts (the year named on January) over long
 * spans, days over short ones, at most `maxTicks` ticks (a narrow chart
 * passes fewer), in the viewer's calendar. Steps align on calendar units,
 * so ticks stay put as the range grows. */
export function dateTicks(
  startMs: number,
  endMs: number,
  maxTicks: number = MAX_DATE_TICKS,
): DateTick[] {
  return (endMs - startMs) / DAY_MS < DAY_MODE_MAX_DAYS
    ? dayTicks(startMs, endMs, maxTicks)
    : monthTicks(startMs, endMs, maxTicks);
}

/** Index of the point closest to (`x`, `y`), the earlier one on a tie, -1
 * for none: what the chart's crosshair snaps to. Both axes count, so records
 * set hours apart (nearly the same x) stay reachable by their height. */
export function nearestPoint(
  points: [number, number][],
  x: number,
  y: number,
): number {
  let best = -1;
  let bestDistance = Infinity;
  points.forEach(([px, py], i) => {
    const distance = (px - x) ** 2 + (py - y) ** 2;
    if (distance < bestDistance) {
      best = i;
      bestDistance = distance;
    }
  });
  return best;
}
