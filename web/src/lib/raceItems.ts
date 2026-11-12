import type { PoolInfo } from "./api";

/**
 * Whether the race items option can be ticked: only on a normal race, and
 * only when the pool holds a seed with the plugin. `hint` explains a disabled
 * option that the pool is the cause of.
 */
export function raceItemsAvailability(
  mode: string,
  pool: PoolInfo | undefined,
): { enabled: boolean; hint: string | null } {
  if (mode !== "normal" || !pool) return { enabled: false, hint: null };
  if (pool.race_items_available > 0) return { enabled: true, hint: null };
  return { enabled: false, hint: "No seed with race items in this pool yet" };
}
