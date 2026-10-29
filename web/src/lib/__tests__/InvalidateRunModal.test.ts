import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/svelte";
import InvalidateRunModal from "$lib/components/InvalidateRunModal.svelte";
import { invalidateSession } from "$lib/api";

vi.mock("$lib/api", async () => {
  const actual = await vi.importActual<typeof import("$lib/api")>("$lib/api");
  return { ...actual, invalidateSession: vi.fn() };
});

describe("InvalidateRunModal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the trimmed typed reason and hands back the session", async () => {
    const updated = { id: "s1", invalidated: true };
    vi.mocked(invalidateSession).mockResolvedValue(updated as never);
    const onDone = vi.fn();
    const { getByRole, getByText } = render(InvalidateRunModal, {
      sessionId: "s1",
      onDone,
      onClose: vi.fn(),
    });

    await fireEvent.input(getByRole("textbox"), {
      target: { value: "  Cheat tool detected  " },
    });
    await fireEvent.click(getByText("Invalidate"));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(updated));
    expect(invalidateSession).toHaveBeenCalledWith("s1", "Cheat tool detected");
  });

  it("refuses a blank reason without calling the server", async () => {
    const { getByRole, getByText } = render(InvalidateRunModal, {
      sessionId: "s1",
      suggestedReason: "   ",
      onDone: vi.fn(),
      onClose: vi.fn(),
    });

    await fireEvent.click(getByText("Invalidate"));

    expect(getByRole("textbox")).toBeTruthy();
    expect(getByText("A reason is required.")).toBeTruthy();
    expect(invalidateSession).not.toHaveBeenCalled();
  });
});
