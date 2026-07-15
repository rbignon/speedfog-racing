import { describe, expect, it, vi, beforeEach } from "vitest";
import { rewards } from "$lib/stores/rewards.svelte";

describe("rewards catalog store", () => {
  beforeEach(() => {
    // Reset module-singleton state between tests.
    rewards.catalog = null;
    vi.unstubAllGlobals();
  });

  it("caches the fetched catalog", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        badges: [
          {
            id: "early_adopter",
            name: "Early Adopter",
            icon_filename: "early_adopter.svg",
            lifecycle: "permanent",
            sort_order: 10,
          },
        ],
        name_templates: [
          {
            id: "default",
            name: "Default",
            color: "#FFFFFF",
            gradient: null,
            background_css: null,
            sort_order: 0,
          },
        ],
        phantom_skins: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await rewards.ensureLoaded();
    expect(rewards.catalog?.badges[0].id).toBe("early_adopter");
    expect(rewards.catalog?.name_templates[0].id).toBe("default");

    // Second call should not refetch.
    await rewards.ensureLoaded();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("lookupBadge returns null for missing or unknown id", async () => {
    rewards.catalog = {
      badges: [
        {
          id: "early_adopter",
          name: "Early Adopter",
          icon_filename: "ea.svg",
          lifecycle: "permanent",
          sort_order: 10,
        },
      ],
      name_templates: [],
      phantom_skins: [],
    };
    expect(rewards.lookupBadge(null)).toBeNull();
    expect(rewards.lookupBadge("nope")).toBeNull();
    expect(rewards.lookupBadge("early_adopter")?.name).toBe("Early Adopter");
  });

  it("lookupTemplate falls back to 'default' when id is null", async () => {
    rewards.catalog = {
      badges: [],
      name_templates: [
        {
          id: "default",
          name: "Default",
          color: "#FFFFFF",
          gradient: null,
          name_css: null,
          background_css: null,
          sort_order: 0,
        },
        {
          id: "daily_crown",
          name: "Daily Crown",
          color: null,
          gradient: ["#FFE9A8", "#C8A44E"],
          name_css: null,
          background_css: null,
          sort_order: 10,
        },
      ],
      phantom_skins: [],
    };
    expect(rewards.lookupTemplate(null)?.id).toBe("default");
    expect(rewards.lookupTemplate(undefined)?.id).toBe("default");
    expect(rewards.lookupTemplate("daily_crown")?.id).toBe("daily_crown");
    expect(rewards.lookupTemplate("nope")).toBeNull();
  });
});

describe("rewards.lookupPhantomSkin", () => {
  beforeEach(() => {
    rewards.catalog = {
      badges: [],
      name_templates: [],
      phantom_skins: [
        {
          id: "gold-aura",
          name: "Gold Aura",
          description: "Top the weekly daily-seed ranking",
          screenshot_filename: "gold-aura.jpg",
          sort_order: 10,
        },
      ],
    };
  });

  it("returns the entry by id", () => {
    expect(rewards.lookupPhantomSkin("gold-aura")?.name).toBe("Gold Aura");
  });

  it("returns null on null/undefined", () => {
    expect(rewards.lookupPhantomSkin(null)).toBeNull();
    expect(rewards.lookupPhantomSkin(undefined)).toBeNull();
  });

  it("returns null when catalog absent", () => {
    rewards.catalog = null;
    expect(rewards.lookupPhantomSkin("gold-aura")).toBeNull();
  });

  it("returns null for unknown id", () => {
    expect(rewards.lookupPhantomSkin("rainbow-aura")).toBeNull();
  });
});
