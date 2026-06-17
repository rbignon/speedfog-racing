import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import PoolTabs from "$lib/components/PoolTabs.svelte";
import type { PoolInfo } from "$lib/api";

function poolInfo(available: number): PoolInfo {
  return {
    available,
    consumed: 0,
    discarded: 0,
    played_by_user: null,
    pool_config: null,
  };
}

function firstTab(container: Element): HTMLButtonElement {
  return container.querySelector("button.pool-tab") as HTMLButtonElement;
}

describe("PoolTabs availability gating", () => {
  it("disables a zero-availability tab by default (race creation context)", () => {
    const { container } = render(PoolTabs, {
      props: {
        pools: [["standard", poolInfo(0)]] as [string, PoolInfo][],
        selected: null,
        onselect: () => {},
      },
    });
    expect(firstTab(container).disabled).toBe(true);
  });

  it("keeps a zero-availability tab clickable when gateAvailability is false (docs context)", () => {
    const onselect = vi.fn();
    const { container } = render(PoolTabs, {
      props: {
        pools: [["standard", poolInfo(0)]] as [string, PoolInfo][],
        selected: null,
        onselect,
        gateAvailability: false,
      },
    });
    const tab = firstTab(container);
    expect(tab.disabled).toBe(false);
    tab.click();
    expect(onselect).toHaveBeenCalledWith("standard");
  });

  it("still honors the global disabled flag even when gating is off", () => {
    const { container } = render(PoolTabs, {
      props: {
        pools: [["standard", poolInfo(5)]] as [string, PoolInfo][],
        selected: null,
        onselect: () => {},
        disabled: true,
        gateAvailability: false,
      },
    });
    expect(firstTab(container).disabled).toBe(true);
  });
});
