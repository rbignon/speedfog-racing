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
