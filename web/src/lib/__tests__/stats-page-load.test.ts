import { describe, expect, it } from "vitest";
import { load } from "../../routes/stats/+page";

function run(search: string) {
  return load({ url: new URL(`http://localhost/stats${search}`) } as never);
}

describe("/stats load", () => {
  it("redirects the retired speedrun tab to /speedrun, whatever else the query holds", () => {
    for (const search of [
      "?tab=speedrun",
      "?pool=sprint&tab=speedrun&sub=random",
    ]) {
      try {
        run(search);
        expect.unreachable("no redirect");
      } catch (e) {
        expect(e).toMatchObject({ status: 307, location: "/speedrun" });
      }
    }
  });

  it("leaves the other tabs alone", () => {
    expect(() => run("")).not.toThrow();
    expect(() => run("?tab=weapons")).not.toThrow();
  });
});
