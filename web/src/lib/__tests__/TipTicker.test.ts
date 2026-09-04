import { fireEvent, render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TipTicker from "$lib/components/TipTicker.svelte";
import { CONTENT_ITEMS } from "$lib/content/items";
import { loadSeenTipIds, SEEN_STORAGE_KEY } from "$lib/content/select";

const ROTATE_MS = 15_000;

function counter(container: HTMLElement): string {
  return container.querySelector(".ticker-count")?.textContent?.trim() ?? "";
}

function title(container: HTMLElement): string {
  return container.querySelector(".tip-title")?.textContent?.trim() ?? "";
}

function nav(container: HTMLElement, dir: "prev" | "next"): HTMLButtonElement {
  return container.querySelector(
    `button[data-tip-nav="${dir}"]`,
  ) as HTMLButtonElement;
}

describe("TipTicker navigation", () => {
  beforeEach(() => {
    localStorage.removeItem(SEEN_STORAGE_KEY);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("steps forward and backward with wrap-around", async () => {
    const { container } = render(TipTicker, { props: { poolName: null } });
    const total = Number(counter(container).split("/")[1]);
    expect(total).toBeGreaterThan(1);
    expect(counter(container)).toBe(`1/${total}`);

    await fireEvent.click(nav(container, "next"));
    expect(counter(container)).toBe(`2/${total}`);

    await fireEvent.click(nav(container, "prev"));
    await fireEvent.click(nav(container, "prev"));
    expect(counter(container)).toBe(`${total}/${total}`);

    await fireEvent.click(nav(container, "next"));
    expect(counter(container)).toBe(`1/${total}`);
  });

  it("restarts the rotation timer after a manual step", async () => {
    const { container } = render(TipTicker, { props: { poolName: null } });

    vi.advanceTimersByTime(ROTATE_MS - 1_000);
    await fireEvent.click(nav(container, "next"));
    const shown = counter(container);

    // The old schedule would have rotated 1 s after the click.
    vi.advanceTimersByTime(ROTATE_MS - 1_000);
    await tick();
    expect(counter(container)).toBe(shown);

    // A full period after the click, rotation resumes.
    vi.advanceTimersByTime(1_000);
    await tick();
    expect(counter(container)).not.toBe(shown);
  });

  it("marks a manually reached tip as seen", async () => {
    const { container } = render(TipTicker, { props: { poolName: null } });
    await fireEvent.click(nav(container, "next"));
    const current = CONTENT_ITEMS.find((i) => i.title === title(container));
    expect(current).toBeDefined();
    expect(loadSeenTipIds(localStorage).has(current!.id)).toBe(true);
  });
});
