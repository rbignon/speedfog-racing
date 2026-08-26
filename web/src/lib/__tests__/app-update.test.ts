import { afterEach, describe, expect, it, vi } from "vitest";
import { AppUpdateStore } from "$lib/stores/appUpdate.svelte";

function bumpedVersion(): string {
  const major = Number(__APP_VERSION__.split(".")[0]);
  return `${major + 1}.0.0`;
}

function stubHealth(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), { status: ok ? 200 : 500 }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppUpdateStore.check", () => {
  it("flips updateAvailable when the server is newer", async () => {
    stubHealth({ status: "ok", version: bumpedVersion() });
    const store = new AppUpdateStore();
    await store.check();
    expect(store.updateAvailable).toBe(true);
  });

  it("stays false for the same version", async () => {
    stubHealth({ status: "ok", version: __APP_VERSION__ });
    const store = new AppUpdateStore();
    await store.check();
    expect(store.updateAvailable).toBe(false);
  });

  it("ignores non-ok responses", async () => {
    stubHealth({ version: bumpedVersion() }, false);
    const store = new AppUpdateStore();
    await store.check();
    expect(store.updateAvailable).toBe(false);
  });

  it("ignores fetch errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    const store = new AppUpdateStore();
    await store.check();
    expect(store.updateAvailable).toBe(false);
  });

  it("dismiss hides until reload", async () => {
    stubHealth({ status: "ok", version: bumpedVersion() });
    const store = new AppUpdateStore();
    await store.check();
    store.dismiss();
    expect(store.dismissed).toBe(true);
  });
});

describe("AppUpdateStore announcement", () => {
  it("exposes the announcement text and link from /health", async () => {
    stubHealth({
      status: "ok",
      version: __APP_VERSION__,
      announcement: "Mods may break on Friday.",
      announcement_url: "/help#faq-game-update",
    });
    const store = new AppUpdateStore();
    await store.check();
    expect(store.announcement).toBe("Mods may break on Friday.");
    expect(store.announcementUrl).toBe("/help#faq-game-update");
  });

  it("clears the announcement once the server stops sending one", async () => {
    stubHealth({
      status: "ok",
      version: __APP_VERSION__,
      announcement: "Old notice",
      announcement_url: null,
    });
    const store = new AppUpdateStore();
    await store.check();
    stubHealth({ status: "ok", version: __APP_VERSION__, announcement: null });
    await store.check();
    expect(store.announcement).toBeNull();
    expect(store.announcementUrl).toBeNull();
  });

  it("drops a blank announcement URL", async () => {
    stubHealth({
      status: "ok",
      version: __APP_VERSION__,
      announcement: "Notice",
      announcement_url: "  ",
    });
    const store = new AppUpdateStore();
    await store.check();
    expect(store.announcementUrl).toBeNull();
  });

  it("treats a blank announcement as none", async () => {
    stubHealth({ status: "ok", version: __APP_VERSION__, announcement: "   " });
    const store = new AppUpdateStore();
    await store.check();
    expect(store.announcement).toBeNull();
  });
});
