import { describe, expect, it } from "vitest";
import { isHttpError, isRedirect } from "@sveltejs/kit";
import { followStep, followTarget } from "$lib/cast/follow";
import { load } from "../../routes/overlay/cast/event/[slug]/[stage]/[scene=castRaceScene]/+page";
import { load as loadRaceLayout } from "../../routes/overlay/cast/race/[id]/+layout";

describe("followStep", () => {
  it("navigates when the stage names another race", () => {
    expect(
      followStep("r1", "finished", { race_id: "r2", done: false }).navigateTo,
    ).toBe("r2");
  });

  it("stays and polls while the shown race is over and nothing replaces it", () => {
    expect(
      followStep("r1", "finished", { race_id: "r1", done: false }),
    ).toEqual({ navigateTo: null, keepPolling: true });
  });

  it("stops once the stage is done on the shown race", () => {
    expect(
      followStep("r1", "finished", { race_id: "r1", done: true }).keepPolling,
    ).toBe(false);
  });

  // A running race is never left, whatever the stage says: nothing can
  // replace it, and a scene flipping away mid-race is the worst outcome.
  it("never polls over a running race", () => {
    expect(followStep("r1", "running", { race_id: "r2", done: false })).toEqual(
      { navigateTo: null, keepPolling: false },
    );
  });

  it("keeps polling through a failed fetch", () => {
    expect(followStep("r1", "finished", null)).toEqual({
      navigateTo: null,
      keepPolling: true,
    });
  });

  it("waits on a stage with no race yet", () => {
    expect(followStep(null, null, { race_id: null, done: false })).toEqual({
      navigateTo: null,
      keepPolling: true,
    });
  });
});

describe("followTarget", () => {
  it("followTarget keeps the query and sets follow", () => {
    const result = followTarget(
      "r2",
      "quad",
      new URLSearchParams("p1=a&cams=2&follow=old:x"),
      { slug: "season-one", stage: "group_g" },
    );
    const url = new URL(result, "http://x");
    expect(url.pathname).toBe("/overlay/cast/race/r2/quad");
    expect(url.searchParams.get("p1")).toBe("a");
    expect(url.searchParams.get("cams")).toBe("2");
    expect(url.searchParams.getAll("follow")).toEqual(["season-one:group_g"]);
  });

  // `hold` only marks a stage URL the race layout fell back to; the race URL
  // that retries the held race must not carry it on.
  it("followTarget drops the hold of a fallback", () => {
    const result = followTarget(
      "r1",
      "quad",
      new URLSearchParams("p1=a&hold=r1&cams=2"),
      { slug: "season-one", stage: "group_g" },
    );
    const url = new URL(result, "http://x");
    expect(url.searchParams.has("hold")).toBe(false);
    expect(url.searchParams.get("cams")).toBe("2");
  });
});

// The stage-keyed scene's load, against a fake API answering the stage's
// current race with `answer` (a Response, or a thrown network error).
async function loadStage(answer: () => Response, query = "p1=a&cams=2") {
  const fetch = async (input: RequestInfo | URL): Promise<Response> => {
    if (
      String(input) === "/api/events/season-one/stages/group_g/current-race"
    ) {
      return answer();
    }
    return new Response("not found", { status: 404 });
  };
  return load({
    params: { slug: "season-one", stage: "group_g", scene: "quad" },
    url: new URL(
      `http://localhost/overlay/cast/event/season-one/group_g/quad?${query}`,
    ),
    fetch,
  } as never);
}

describe("stage-keyed scene load", () => {
  it("hands over to the stage's current race, following the stage", async () => {
    const thrown = await loadStage(() =>
      Response.json({ race_id: "r2", done: false }),
    ).catch((e: unknown) => e);
    expect(isRedirect(thrown)).toBe(true);
    const url = new URL((thrown as { location: string }).location, "http://x");
    expect(url.pathname).toBe("/overlay/cast/race/r2/quad");
    expect(url.searchParams.get("p1")).toBe("a");
    expect(url.searchParams.get("follow")).toBe("season-one:group_g");
  });

  // On air, a scene must show its plate rather than an error page: an
  // unreachable or failing endpoint is "no answer yet".
  it.each([
    [
      "a stage with no race yet",
      () => Response.json({ race_id: null, done: false }),
    ],
    ["a server error", () => new Response("boom", { status: 500 })],
    ["an unknown stage", () => new Response("nope", { status: 404 })],
    [
      "an unreachable server",
      () => {
        throw new TypeError("Failed to fetch");
      },
    ],
  ])("waits on the plate for %s", async (_, answer) => {
    expect(await loadStage(answer)).toMatchObject({
      scene: "quad",
      slug: "season-one",
      stage: "group_g",
    });
  });

  // The race layout fell back here because race r1 would not load: going
  // straight back would bounce between the two routes, so the plate waits
  // and its poll retries r1 a beat later.
  it("waits on the plate when the stage names the race it holds", async () => {
    expect(
      await loadStage(
        () => Response.json({ race_id: "r1", done: false }),
        "p1=a&cams=2&hold=r1",
      ),
    ).toMatchObject({ scene: "quad" });
  });

  it("hands over at once when the stage names another race than the one held", async () => {
    const thrown = await loadStage(
      () => Response.json({ race_id: "r2", done: false }),
      "p1=a&cams=2&hold=r1",
    ).catch((e: unknown) => e);
    expect(isRedirect(thrown)).toBe(true);
    const url = new URL((thrown as { location: string }).location, "http://x");
    expect(url.pathname).toBe("/overlay/cast/race/r2/quad");
    expect(url.searchParams.has("hold")).toBe(false);
  });
});

// The race scenes' layout load, against an API where race r1 will not load
// (deleted, or the server failing).
async function loadRace(query: string, path = "/overlay/cast/race/r1/quad") {
  const fetch = async (): Promise<Response> =>
    new Response("boom", { status: 500 });
  return loadRaceLayout({
    params: { id: "r1" },
    url: new URL(`http://localhost${path}?${query}`),
    fetch,
  } as never);
}

describe("race scene load", () => {
  it("falls back to the followed stage's plate when its race cannot load", async () => {
    const thrown = await loadRace(
      "p1=a&follow=season-one:group_g&cams=2",
    ).catch((e: unknown) => e);
    expect(isRedirect(thrown)).toBe(true);
    const url = new URL((thrown as { location: string }).location, "http://x");
    expect(url.pathname).toBe("/overlay/cast/event/season-one/group_g/quad");
    expect(url.searchParams.get("p1")).toBe("a");
    expect(url.searchParams.get("cams")).toBe("2");
    expect(url.searchParams.has("follow")).toBe(false);
    expect(url.searchParams.get("hold")).toBe("r1");
  });

  // A pasted URL can end in a slash: the scene is still the last segment, not
  // an empty one that would land on no route.
  it("keeps the scene of a URL with a trailing slash", async () => {
    const thrown = await loadRace(
      "follow=season-one:group_g",
      "/overlay/cast/race/r1/duel/",
    ).catch((e: unknown) => e);
    expect(isRedirect(thrown)).toBe(true);
    const url = new URL((thrown as { location: string }).location, "http://x");
    expect(url.pathname).toBe("/overlay/cast/event/season-one/group_g/duel");
  });

  it("is a 404 without a stage to follow", async () => {
    const thrown = await loadRace("p1=a&cams=2").catch((e: unknown) => e);
    expect(isHttpError(thrown, 404)).toBe(true);
  });
});

// The race layout load of race `raceId` with `?event=<slug>`, against an API
// that serves any race and answers the event detail with `eventAnswer`;
// `calls` counts the event detail requests.
async function loadCoBranded(
  raceId: string,
  slug: string,
  eventAnswer: () => Response,
  calls: { event: number },
) {
  const fetch = async (input: RequestInfo | URL): Promise<Response> => {
    const path = String(input);
    if (path === `/api/events/${slug}`) {
      calls.event += 1;
      return eventAnswer();
    }
    if (path.startsWith("/api/races/")) {
      return Response.json({ id: path.split("/").pop(), status: "setup" });
    }
    return new Response("not found", { status: 404 });
  };
  return loadRaceLayout({
    params: { id: raceId },
    url: new URL(
      `http://localhost/overlay/cast/race/${raceId}/quad?event=${slug}`,
    ),
    fetch,
  } as never);
}

describe("race scene co-brand", () => {
  // Every follow hand-over re-runs the layout load in the same page: the
  // heavy event detail is read once for the page's life, not once per race.
  it("reads the event detail once across hand-overs", async () => {
    const calls = { event: 0 };
    const answer = () => Response.json({ partner_name: "Ignite" });
    const first = await loadCoBranded("r1", "memo-once", answer, calls);
    const second = await loadCoBranded("r2", "memo-once", answer, calls);
    expect(calls.event).toBe(1);
    expect(first).toMatchObject({ partnerName: "Ignite" });
    expect(second).toMatchObject({ partnerName: "Ignite" });
  });

  it("retries the event detail after a failure", async () => {
    const calls = { event: 0 };
    const answers = [
      () => new Response("boom", { status: 500 }),
      () => Response.json({ partner_name: "Ignite" }),
    ];
    const answer = () => answers[calls.event - 1]();
    const first = await loadCoBranded("r1", "memo-retry", answer, calls);
    const second = await loadCoBranded("r2", "memo-retry", answer, calls);
    expect(calls.event).toBe(2);
    expect(first).toMatchObject({ partnerName: null });
    expect(second).toMatchObject({ partnerName: "Ignite" });
  });
});
