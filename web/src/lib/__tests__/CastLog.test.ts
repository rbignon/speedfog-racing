import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastLog from "$lib/components/cast/CastLog.svelte";
import type { CastLogKind, CastLogRow } from "$lib/cast/log";

const rect = { x: 16, y: 834, w: 900, h: 230 };

function row(kind: CastLogKind, over: Partial<CastLogRow> = {}): CastLogRow {
  return {
    id: "p-1",
    kind,
    name: "Alice",
    colorIndex: 0,
    zone: kind === "zone" ? "Stormveil Castle" : "",
    igtMs: 3_270_000,
    ...over,
  };
}

function lineOf(r: CastLogRow): string | null | undefined {
  const { container } = render(CastLog, { props: { rows: [r], rect } });
  return container
    .querySelector(".fe")
    ?.textContent?.replace(/\s+/g, " ")
    .trim();
}

describe("CastLog: rows", () => {
  it("names the zone a runner entered", () => {
    expect(lineOf(row("zone"))).toBe("→ Stormveil Castle");
  });

  it("says where a runner died", () => {
    expect(lineOf(row("zone", { deaths: 1 }))).toBe("died in Stormveil Castle");
  });

  it.each([
    ["finish", "finished"],
    ["dnf", "DNF"],
    ["dq", "DQ"],
  ] as const)("reports a %s outcome as %s", (kind, text) => {
    expect(lineOf(row(kind))).toBe(text);
  });

  it("keeps a runner's outcome and their entry at the same time apart", () => {
    const { container } = render(CastLog, {
      props: { rows: [row("finish"), row("zone")], rect },
    });
    expect(container.querySelectorAll(".fl")).toHaveLength(2);
  });
});
