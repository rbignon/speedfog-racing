import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ModeStats from "../components/ModeStats.svelte";
import type { UserPoolStatsEntry } from "$lib/api";

function pool(
  name: string,
  runs: number,
  best: number | null,
): UserPoolStatsEntry {
  return {
    pool_name: name,
    pool_display_name: name,
    total_runs: runs,
    race: { runs: Math.floor(runs / 2), best_time_ms: best },
    training: { runs: Math.ceil(runs / 2), best_time_ms: best },
  } as unknown as UserPoolStatsEntry;
}

describe("ModeStats", () => {
  it("renders the most-played mode as the hero, others as pills", () => {
    const pools = [
      pool("Standard", 90, 2_194_000),
      pool("Boss Shuffle", 34, 2_010_000),
      pool("Boss Rush", 20, 1_954_000),
    ];
    render(ModeStats, { pools });

    expect(screen.queryByText("MOST PLAYED")).not.toBeNull();
    expect(screen.queryByText("Standard")).not.toBeNull();
    expect(screen.queryByText("Boss Shuffle")).not.toBeNull();
    expect(screen.queryByText("Boss Rush")).not.toBeNull();
  });

  it("hides the pills column when only one mode has runs", () => {
    const pools = [pool("Standard", 90, 2_194_000)];
    const { container } = render(ModeStats, { pools });

    expect(screen.queryByText("Standard")).not.toBeNull();
    expect(container.querySelector(".pills")).toBeNull();
  });

  it("renders nothing when there are no pools", () => {
    const { container } = render(ModeStats, { pools: [] });
    expect(container.textContent?.trim()).toBe("");
  });
});
