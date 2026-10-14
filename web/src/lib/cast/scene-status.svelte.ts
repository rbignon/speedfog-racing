import { sceneRaceStatus } from "$lib/cast/clock";

interface SceneRace {
  status: string;
  startedAt: string | null;
  /** The scene's `delay`: its clock runs that far behind the real one. */
  delayMs: number;
}

/**
 * The race status a cast scene shows (`sceneRaceStatus`), switching from
 * "setup" to "running" at the very end of the start countdown rather than at
 * the start command. No clock ticks for it: one timer, set while a countdown
 * is on, wakes the status up when it ends. Call it while the scene
 * initialises; `read` is tracked like a `$derived`.
 */
export function sceneStatus(read: () => SceneRace): {
  readonly current: string;
} {
  let now = $state(Date.now());
  $effect(() => {
    const { status, startedAt, delayMs } = read();
    if (status !== "running" || !startedAt) return;
    const start = Date.parse(startedAt);
    let id: ReturnType<typeof setTimeout> | undefined;
    // Fresh at once (the start can arrive long after the scene mounted),
    // then once more when the countdown ends; again if the wall clock
    // stepped back meanwhile, the timer running on its own clock.
    const wake = () => {
      now = Date.now();
      const left = start - (now - delayMs);
      if (left > 0) id = setTimeout(wake, left + 1);
    };
    wake();
    return () => clearTimeout(id);
  });
  return {
    get current() {
      const { status, startedAt, delayMs } = read();
      return sceneRaceStatus(status, startedAt, now - delayMs);
    },
  };
}
