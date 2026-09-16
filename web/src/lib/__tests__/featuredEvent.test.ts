import { afterEach, describe, expect, it, vi } from "vitest";
import { featuredEvent } from "$lib/stores/featuredEvent.svelte";
import type { EventSummary } from "$lib/api";

function deferred() {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((r) => (resolve = r));
  return { promise, resolve };
}

function response(events: Partial<EventSummary>[]) {
  return { ok: true, json: async () => events };
}

describe("featuredEvent store", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("drops a response overtaken by a later request", async () => {
    // The layout refreshes again as soon as the login lands: the anonymous
    // answer, arriving last, must not overwrite the signed-in one.
    const anonymous = deferred();
    const signedIn = deferred();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(anonymous.promise)
        .mockReturnValueOnce(signedIn.promise),
    );
    const first = featuredEvent.refresh();
    const second = featuredEvent.refresh();
    signedIn.resolve(response([{ slug: "season-one", my_signup: true }]));
    await second;
    anonymous.resolve(response([{ slug: "season-one", my_signup: false }]));
    await first;
    expect(featuredEvent.current?.my_signup).toBe(true);
  });

  it("keeps the last list when a refresh fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(response([{ slug: "season-one" }])),
    );
    await featuredEvent.refresh();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await featuredEvent.refresh();
    expect(featuredEvent.current?.slug).toBe("season-one");
  });
});
