import { describe, expect, it } from "vitest";

import {
  chatSidebarLayout,
  type ChatSidebarInputs,
} from "$lib/chat-sidebar-layout";

function layout(overrides: Partial<ChatSidebarInputs> = {}) {
  return chatSidebarLayout({
    publicAccess: "readable",
    participantsAccess: false,
    activeTab: "public",
    ...overrides,
  });
}

describe("chatSidebarLayout", () => {
  describe("single-pane (no participants access)", () => {
    it("hides tabs and forces public", () => {
      const r = layout({ participantsAccess: false });
      expect(r.showTabs).toBe(false);
      expect(r.effectiveTab).toBe("public");
      expect(r.publicTabDisabled).toBe(false);
    });

    it("overrides activeTab=participants to public when tabs are hidden", () => {
      // Defensive: parent might pass a stale activeTab.
      const r = layout({
        participantsAccess: false,
        activeTab: "participants",
      });
      expect(r.effectiveTab).toBe("public");
    });

    it("does not mark the public tab disabled when there is no tab bar", () => {
      const r = layout({ participantsAccess: false, publicAccess: "locked" });
      expect(r.publicTabDisabled).toBe(false);
    });

    it("shows the locked pane when public is locked", () => {
      const r = layout({ participantsAccess: false, publicAccess: "locked" });
      expect(r.showLockedPane).toBe(true);
    });

    it("shows messages when public is readable", () => {
      const r = layout({ participantsAccess: false, publicAccess: "readable" });
      expect(r.showLockedPane).toBe(false);
    });
  });

  describe("two-tab (participants access)", () => {
    it("shows tabs and respects activeTab", () => {
      const r = layout({ participantsAccess: true, activeTab: "participants" });
      expect(r.showTabs).toBe(true);
      expect(r.effectiveTab).toBe("participants");
    });

    it("disables the public tab when locked", () => {
      const r = layout({
        participantsAccess: true,
        activeTab: "participants",
        publicAccess: "locked",
      });
      expect(r.publicTabDisabled).toBe(true);
      // Active tab is participants, so no locked pane shown.
      expect(r.showLockedPane).toBe(false);
    });

    it("shows the locked pane when active tab is public and public is locked", () => {
      // Defensive: parent is supposed to keep activeTab on participants
      // while public is locked, but we still render correctly if it does
      // not.
      const r = layout({
        participantsAccess: true,
        activeTab: "public",
        publicAccess: "locked",
      });
      expect(r.showLockedPane).toBe(true);
      expect(r.publicTabDisabled).toBe(true);
    });

    it("shows public messages when public is readable and active", () => {
      const r = layout({
        participantsAccess: true,
        activeTab: "public",
        publicAccess: "readable",
      });
      expect(r.showLockedPane).toBe(false);
      expect(r.publicTabDisabled).toBe(false);
    });
  });

  describe("showPublicOnly (Daily Seeds)", () => {
    it("hides tabs even when participants access exists", () => {
      const r = layout({
        participantsAccess: true,
        showPublicOnly: true,
        activeTab: "participants",
      });
      expect(r.showTabs).toBe(false);
      expect(r.effectiveTab).toBe("public");
    });

    it("does not bypass the public lock", () => {
      const r = layout({
        participantsAccess: true,
        showPublicOnly: true,
        activeTab: "public",
        publicAccess: "locked",
      });
      expect(r.showLockedPane).toBe(true);
    });

    it("still works for an anonymous viewer (no participants access)", () => {
      // Daily Seed for a logged-out viewer: single pane, lock honored.
      const r = layout({
        participantsAccess: false,
        showPublicOnly: true,
        publicAccess: "locked",
      });
      expect(r.showTabs).toBe(false);
      expect(r.showLockedPane).toBe(true);
    });
  });
});
