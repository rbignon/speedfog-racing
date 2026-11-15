import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import UnrankedChip from "$lib/components/UnrankedChip.svelte";

const REASON =
  "Reset race: its runners already played this seed, so this race does not count on the Speedrun boards.";

describe("UnrankedChip", () => {
  it("describes a keyboard-reachable chip", () => {
    render(UnrankedChip, { props: { reason: REASON } });

    const trigger = screen.getByText("Unranked").closest("[tabindex]");
    expect(trigger?.getAttribute("tabindex")).toBe("0");
    expect(trigger?.getAttribute("aria-describedby")).toBe(
      screen.getByRole("tooltip").id,
    );
  });

  it("dismisses the open tooltip with Escape by blurring the chip", async () => {
    render(UnrankedChip, { props: { reason: REASON } });

    const chip = screen
      .getByText("Unranked")
      .closest<HTMLElement>("[tabindex]")!;
    chip.focus();
    expect(document.activeElement).toBe(chip);

    await fireEvent.keyDown(chip, { key: "Escape" });

    expect(document.activeElement).not.toBe(chip);
  });
});
