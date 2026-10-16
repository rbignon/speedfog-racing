import { describe, expect, it } from "vitest";
import { isRedirect } from "@sveltejs/kit";
import { followStep, followTarget } from "$lib/cast/follow";
import { load } from "../../routes/overlay/cast/event/[slug]/[stage]/[scene=castRaceScene]/+page";

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
});

// The stage-keyed scene's load, against a fake API answering the stage's
// current race with `answer` (a Response, or a thrown network error).
async function loadStage(answer: () => Response) {
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
      "http://localhost/overlay/cast/event/season-one/group_g/quad?p1=a&cams=2",
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
});
