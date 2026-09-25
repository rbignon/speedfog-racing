/**
 * Holds incoming updates back so the data on screen matches video that is
 * seconds behind. Equal timeouts fire in the order they were set, so the
 * queue needs no sequence of its own.
 */
export interface DelayQueue {
  push(apply: () => void, opts?: { immediate?: boolean }): void;
  clear(): void;
}

export function createDelayQueue(delayMs: number): DelayQueue {
  const pending = new Set<ReturnType<typeof setTimeout>>();
  return {
    push(apply, opts) {
      if (delayMs <= 0 || opts?.immediate) {
        apply();
        return;
      }
      const id = setTimeout(() => {
        pending.delete(id);
        apply();
      }, delayMs);
      pending.add(id);
    },
    clear() {
      for (const id of pending) clearTimeout(id);
      pending.clear();
    },
  };
}
