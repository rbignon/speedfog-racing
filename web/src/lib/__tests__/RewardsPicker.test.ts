import { describe, expect, it, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import RewardsPicker from "$lib/components/RewardsPicker.svelte";
import { rewards } from "$lib/stores/rewards.svelte";
import type { AuthUser, MyInventoryDto } from "$lib/api";

const seedCatalog = () => {
  rewards.catalog = {
    badges: [
      {
        id: "early_adopter",
        name: "Early Adopter",
        description: "Joined in the first season.",
        icon_filename: "early_adopter.svg",
        lifecycle: "permanent",
        sort_order: 10,
      },
      {
        id: "contributor",
        name: "Contributor",
        description: "Submitted a merged PR.",
        icon_filename: "contributor.svg",
        lifecycle: "permanent",
        sort_order: 20,
      },
    ],
    name_templates: [
      {
        id: "default",
        name: "Default",
        description: "Plain username.",
        color: "#FFFFFF",
        gradient: null,
        name_css: null,
        background_css: null,
        sort_order: 0,
      },
      {
        id: "elo_crown",
        name: "ELO Crown",
        description: "Top 3 ELO holders.",
        color: null,
        gradient: ["#FFE9A8", "#C8A44E"],
        name_css: null,
        background_css: "linear-gradient(90deg, #2a2410, #1c180b)",
        sort_order: 10,
      },
    ],
  };
};

const baseUser: AuthUser = {
  id: "u1",
  twitch_username: "alice",
  twitch_display_name: "Alice",
  twitch_avatar_url: "https://cdn/test.png",
  role: "player",
  locale: "en",
  overlay_settings: null,
  feedback_prompted_at: null,
};

const baseInventory: MyInventoryDto = {
  held_badges: [
    {
      id: "early_adopter",
      name: "Early Adopter",
      icon_filename: "early_adopter.svg",
    },
    {
      id: "contributor",
      name: "Contributor",
      icon_filename: "contributor.svg",
    },
  ],
  unlocked_templates: [
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
      id: "elo_crown",
      name: "ELO Crown",
      color: null,
      gradient: ["#FFE9A8", "#C8A44E"],
      name_css: null,
      background_css: "linear-gradient(90deg, #2a2410, #1c180b)",
      sort_order: 10,
    },
  ],
  equipped_badge_id: "early_adopter",
  equipped_name_template_id: "elo_crown",
};

describe("RewardsPicker", () => {
  beforeEach(() => {
    rewards.catalog = null;
  });

  it("renders one badge tile per held badge plus a 'None' tile", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: "early_adopter",
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    expect(tiles.length).toBe(baseInventory.held_badges.length + 1);
    // First tile is the "None" tile.
    expect(tiles[0].textContent).toContain("None");
  });

  it("renders one row per unlocked template", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: null,
      },
    });
    const rows = container.querySelectorAll(".template-row");
    expect(rows.length).toBe(baseInventory.unlocked_templates.length);
  });

  it("marks the equipped badge with an 'Active' pastille", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: "contributor",
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    // baseInventory.equipped_badge_id = "early_adopter": index 1 (after None tile).
    expect(tiles[1].textContent).toContain("Active");
    expect(tiles[2].textContent).not.toContain("Active");
  });

  it("marks the equipped template with an 'Active' pastille", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const rows = container.querySelectorAll(".template-row");
    // equipped_name_template_id = "elo_crown" (index 1).
    expect(rows[0].textContent).not.toContain("Active");
    expect(rows[1].textContent).toContain("Active");
  });

  it("marks the 'None' tile as Active when no badge is equipped", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: { ...baseInventory, equipped_badge_id: null },
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    expect(tiles[0].textContent).toContain("Active");
  });

  it("toggles the 'selected' outline on click", async () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: "early_adopter",
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    expect(tiles[1].classList.contains("selected")).toBe(true);
    await fireEvent.click(tiles[2]);
    expect(tiles[1].classList.contains("selected")).toBe(false);
    expect(tiles[2].classList.contains("selected")).toBe(true);
  });

  it("clicking the 'None' tile clears the badge selection", async () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: "early_adopter",
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    await fireEvent.click(tiles[0]);
    expect(tiles[0].classList.contains("selected")).toBe(true);
  });

  it("clicking a template row updates the preview style", async () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const preview = container.querySelector(".preview") as HTMLElement;
    expect(preview.getAttribute("style") ?? "").not.toContain(
      "linear-gradient",
    );
    const rows = container.querySelectorAll(".template-row");
    await fireEvent.click(rows[1]);
    expect(preview.getAttribute("style") ?? "").toContain("linear-gradient");
  });

  it("preview uses selection, independent of equipped_*", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        // Server says equipped is elo_crown / early_adopter, but selection is default / null.
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const preview = container.querySelector(".preview") as HTMLElement;
    // Default has no background_css, so the inline style should not include linear-gradient.
    expect(preview.getAttribute("style") ?? "").not.toContain(
      "linear-gradient",
    );
    // No badge image in preview.
    expect(preview.querySelector(".preview-badge")).toBeNull();
  });

  it("does not apply any inline color for the 'default' template (matches UserLink)", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const previewName = container.querySelector(".preview-name") as HTMLElement;
    // Default template falls back to inherited color, so no inline style should be set.
    expect(previewName.getAttribute("style") ?? "").toBe("");
    // Same for the Default row's name in the list.
    const firstRowName = container.querySelector(
      ".template-row .template-name",
    ) as HTMLElement;
    expect(firstRowName.getAttribute("style") ?? "").toBe("");
  });

  it("template name span has intrinsic width (no flex stretch)", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "elo_crown",
        selectedBadgeId: null,
      },
    });
    // The fix: .template-name renders inline-block; the gradient is applied
    // via background + background-clip:text on the span itself.
    const nameSpan = container.querySelectorAll(".template-name")[1];
    const style = nameSpan?.getAttribute("style") ?? "";
    expect(style).toContain("linear-gradient");
    expect(style).toContain("background-clip: text");
  });

  it("badge tiles expose description via title attribute", () => {
    seedCatalog();
    const { container } = render(RewardsPicker, {
      props: {
        inventory: baseInventory,
        user: baseUser,
        selectedTemplateId: "default",
        selectedBadgeId: null,
      },
    });
    const tiles = container.querySelectorAll(".badge-tile");
    expect(tiles[1].getAttribute("title")).toBe("Joined in the first season.");
    expect(tiles[2].getAttribute("title")).toBe("Submitted a merged PR.");
  });
});
