import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import { parseCastParams } from "$lib/cast/params";

vi.mock("$app/state", () => ({
  page: {
    url: new URL(
      "http://localhost/overlay/cast/event/season-one/group_b/talk?cams=2",
    ),
  },
}));

import TalkScene from "../../routes/overlay/cast/event/[slug]/[stage]/talk/+page.svelte";

function entry(name: string, points: number) {
  return {
    user: {
      id: name,
      twitch_username: name,
      twitch_display_name: name,
      twitch_avatar_url: null,
    },
    newcomer: false,
    points,
    igt_total: 0,
    advances: false,
    signature_weapon: null,
  };
}

// Race 1 is over (ana 1st, bob 2nd) and race 2 is live: bob has finished it,
// ana is still on course, provisionally on 0 in `results`.
const STAGE = {
  key: "group_b",
  label: "Group B",
  kind: "round",
  bracket: "main",
  date: null,
  date_fixed: false,
  time_set: false,
  from: [],
  advance: 1,
  races_expected: 3,
  complete: false,
  walkover: false,
  modes: ["standard", "boss_rush", "standard"],
  races: [],
  results: [entry("bob", 170), entry("ana", 100)],
  settled_results: [entry("ana", 100), entry("bob", 70)],
  field: [],
};

describe("cast talk scene: standings", () => {
  // The panel says "After N of M races": a live race's provisional zeros
  // under it would read as runners who scored nothing.
  it("lists the standings after the finished races alone", () => {
    const { container } = render(TalkScene, {
      props: {
        data: {
          event: { slug: "season-one", stages: [STAGE], partner_name: null },
          stage: STAGE,
          casters: [null, null],
          castParams: parseCastParams(new URL("http://localhost/?cams=2")),
        },
      } as never,
    });
    const rows = [...container.querySelectorAll(".srow")].map((row) => [
      row.querySelector(".sn")?.textContent,
      row.querySelector(".sp")?.textContent,
    ]);
    expect(rows).toEqual([
      ["ana", "100"],
      ["bob", "70"],
    ]);
  });
});
