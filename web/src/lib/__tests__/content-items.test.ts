import { describe, expect, it } from "vitest";
import { CONTENT_ITEMS } from "$lib/content/items";
import { GAME_CHANGE_CATEGORIES } from "$lib/content/types";

describe("content catalog invariants", () => {
  it("has unique ids", () => {
    const ids = CONTENT_ITEMS.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("has non-empty title and short on every item", () => {
    for (const item of CONTENT_ITEMS) {
      expect(item.title.trim().length, item.id).toBeGreaterThan(0);
      expect(item.short.trim().length, item.id).toBeGreaterThan(0);
    }
  });

  it("gives every game_change a valid category and no tip a category", () => {
    for (const item of CONTENT_ITEMS) {
      if (item.kind === "game_change") {
        expect(GAME_CHANGE_CATEGORIES, item.id).toContain(item.category);
      } else {
        expect(item.category, item.id).toBeUndefined();
      }
    }
  });

  it("gives every tip a level and no game_change a level", () => {
    for (const item of CONTENT_ITEMS) {
      if (item.kind === "tip") {
        expect(["beginner", "advanced"], item.id).toContain(item.level);
      } else {
        expect(item.level, item.id).toBeUndefined();
      }
    }
  });

  it("uses snake_case pool keys in pools tags", () => {
    for (const item of CONTENT_ITEMS) {
      for (const pool of item.pools ?? []) {
        expect(pool, item.id).toMatch(/^[a-z0-9_]+$/);
      }
      if (item.pools) {
        expect(item.pools.length, item.id).toBeGreaterThan(0);
      }
    }
  });

  it("never sets pools on game_change items (the Game Changes page renders them unconditionally)", () => {
    for (const item of CONTENT_ITEMS) {
      if (item.kind === "game_change") {
        expect(item.pools, item.id).toBeUndefined();
      }
    }
  });

  it("never uses an em dash in player-facing strings", () => {
    for (const item of CONTENT_ITEMS) {
      const text = [item.title, item.short, item.body ?? ""].join(" ");
      expect(text.includes("—"), item.id).toBe(false);
    }
  });

  it("keeps emphasis markers balanced and non-empty in short and body", () => {
    for (const item of CONTENT_ITEMS) {
      for (const text of [item.short, item.body ?? ""]) {
        const markers = text.split("**").length - 1;
        expect(markers % 2, `${item.id}: unbalanced ** markers`).toBe(0);
        expect(text.includes("****"), `${item.id}: empty bold span`).toBe(
          false,
        );
      }
    }
  });

  it("never uses emphasis markers in titles (titles are already styled)", () => {
    for (const item of CONTENT_ITEMS) {
      expect(item.title.includes("**"), item.id).toBe(false);
    }
  });
});
