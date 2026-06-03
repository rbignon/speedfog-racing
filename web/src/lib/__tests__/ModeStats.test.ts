import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ModeStats from "../components/ModeStats.svelte";
import type { UserPoolStatsEntry } from "$lib/api";

function pool(
  name: string,
  runs: number,
  best: number | null,
  displayName: string | null = null,
): UserPoolStatsEntry {
  return {
    pool_name: name,
    pool_display_name: displayName,
    total_runs: runs,
    race: { runs: Math.floor(runs / 2), best_time_ms: best },
    training: { runs: Math.ceil(runs / 2), best_time_ms: best },
  };
}

describe("ModeStats", () => {
  it("renders the most-played mode as the hero, others as pills", () => {
    const pools = [
      pool("standard", 90, 2_194_000),
      pool("boss_shuffle", 34, 2_010_000),
      pool("boss_rush", 20, 1_954_000),
    ];
    render(ModeStats, { pools });

    expect(screen.queryByText("MOST PLAYED")).not.toBeNull();
    expect(screen.queryByText("Standard")).not.toBeNull();
    expect(screen.queryByText("Boss Shuffle")).not.toBeNull();
    expect(screen.queryByText("Boss Rush")).not.toBeNull();
  });

  it("hides the pills column when only one mode has runs", () => {
    const pools = [pool("standard", 90, 2_194_000)];
    const { container } = render(ModeStats, { pools });

    expect(screen.queryByText("Standard")).not.toBeNull();
    expect(container.querySelector(".pills")).toBeNull();
  });

  it("renders nothing when there are no pools", () => {
    const { container } = render(ModeStats, { pools: [] });
    expect(container.textContent?.trim()).toBe("");
  });

  it("prefers the configured display name over the title-cased pool name", () => {
    const pools = [pool("uwyg_boss_rush", 12, 1_900_000, "UWYG Boss Rush")];
    render(ModeStats, { pools });

    expect(screen.queryByText("UWYG Boss Rush")).not.toBeNull();
    // The title-cased fallback ("Uwyg Boss Rush") must not be shown.
    expect(screen.queryByText("Uwyg Boss Rush")).toBeNull();
  });
});
