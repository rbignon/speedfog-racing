import { describe, expect, it } from "vitest";
import { load } from "../../routes/overlay/cast/event/[slug]/[stage]/talk/+page";

const EVENT = {
  slug: "season-one",
  stages: [{ key: "group_b", label: "Group B", races: [] }],
  showcases: [],
};

// The API as the talk scene's load sees it: the event, and one registered
// caster, everyone else unknown to the site.
async function fakeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  if (url === "/api/events/season-one") return Response.json(EVENT);
  if (url === "/api/users/fogcaster") {
    return Response.json({
      twitch_username: "fogcaster",
      twitch_display_name: "FogCaster",
    });
  }
  return new Response("not found", { status: 404 });
}

async function castersFor(query: string) {
  const data = await load({
    params: { slug: "season-one", stage: "group_b" },
    url: new URL(
      `http://localhost/overlay/cast/event/season-one/group_b/talk?${query}`,
    ),
    fetch: fakeFetch,
  } as never);
  return (data as { casters: [string | null, string | null] }).casters;
}

describe("talk scene load: casters", () => {
  it("names a registered caster by their display name", async () => {
    expect(await castersFor("c1=fogcaster")).toEqual(["FogCaster", null]);
  });

  // A caster needs no account on the site: the race scenes print the name
  // the URL gives, and so must the talk scene.
  it("prints a name the site does not know as written", async () => {
    expect(await castersFor("c1=fogcaster&c2=Jane Doe")).toEqual([
      "FogCaster",
      "Jane Doe",
    ]);
  });
});
