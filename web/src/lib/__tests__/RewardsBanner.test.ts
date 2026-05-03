import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import RewardsBanner from "$lib/components/RewardsBanner.svelte";

describe("RewardsBanner", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    // Provide a fake token so fetchRewardNotifications does not bail early.
    localStorage.setItem("speedfog_token", "fake-token-for-tests");
  });

  it("renders nothing when there are no pending notifications", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => [] }),
    );
    const { container } = render(RewardsBanner);
    // Wait for onMount fetch.
    await new Promise((r) => setTimeout(r, 0));
    expect(
      container.querySelector('[data-testid="rewards-banner"]'),
    ).toBeNull();
  });

  it("shows an unlock summary when grants are pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: "1",
            kind: "badge_granted",
            reward_id: "early_adopter",
            created_at: "2026-04-30T10:00:00Z",
          },
        ],
      }),
    );
    render(RewardsBanner);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/unlocked/i)).not.toBeNull();
  });

  it("shows a revoke summary when only revokes are pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: "1",
            kind: "badge_revoked",
            reward_id: "top1_elo",
            created_at: "2026-04-30T10:00:00Z",
          },
        ],
      }),
    );
    render(RewardsBanner);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/lost/i)).not.toBeNull();
  });

  it("counts phantom_skin_unlocked alongside other grants", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: "1",
            kind: "phantom_skin_unlocked",
            reward_id: "emerald-aura",
            created_at: "2026-05-02T11:28:33Z",
          },
          {
            id: "2",
            kind: "badge_granted",
            reward_id: "veteran",
            created_at: "2026-05-02T11:28:33Z",
          },
        ],
      }),
    );
    render(RewardsBanner);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/2 rewards unlocked/i)).not.toBeNull();
  });

  it("shows mixed summary when both grants and revokes are pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: "1",
            kind: "badge_granted",
            reward_id: "contributor",
            created_at: "2026-04-30T10:00:00Z",
          },
          {
            id: "2",
            kind: "badge_revoked",
            reward_id: "top1_elo",
            created_at: "2026-04-30T10:01:00Z",
          },
        ],
      }),
    );
    render(RewardsBanner);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/unlocked/i)).not.toBeNull();
    expect(screen.queryByText(/lost/i)).not.toBeNull();
  });
});
