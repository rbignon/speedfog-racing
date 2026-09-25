import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createDelayQueue } from "$lib/cast/delay";

describe("createDelayQueue", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("applies straight away when no delay is asked for", () => {
    const seen: number[] = [];
    const q = createDelayQueue(0);
    q.push(() => seen.push(1));
    expect(seen).toEqual([1]);
  });

  it("holds an update back for the whole delay", () => {
    const seen: number[] = [];
    const q = createDelayQueue(8000);
    q.push(() => seen.push(1));
    vi.advanceTimersByTime(7999);
    expect(seen).toEqual([]);
    vi.advanceTimersByTime(1);
    expect(seen).toEqual([1]);
  });

  it("keeps the order the updates arrived in", () => {
    const seen: number[] = [];
    const q = createDelayQueue(5000);
    q.push(() => seen.push(1));
    vi.advanceTimersByTime(1000);
    q.push(() => seen.push(2));
    vi.advanceTimersByTime(1000);
    q.push(() => seen.push(3));
    vi.advanceTimersByTime(10000);
    expect(seen).toEqual([1, 2, 3]);
  });

  it("lets the first state through at once so the overlay never starts blank", () => {
    const seen: string[] = [];
    const q = createDelayQueue(8000);
    q.push(() => seen.push("state"), { immediate: true });
    expect(seen).toEqual(["state"]);
    q.push(() => seen.push("update"));
    expect(seen).toEqual(["state"]);
    vi.advanceTimersByTime(8000);
    expect(seen).toEqual(["state", "update"]);
  });

  it("drops what is still pending when the connection goes away", () => {
    const seen: number[] = [];
    const q = createDelayQueue(5000);
    q.push(() => seen.push(1));
    q.clear();
    vi.advanceTimersByTime(10000);
    expect(seen).toEqual([]);
  });
});
