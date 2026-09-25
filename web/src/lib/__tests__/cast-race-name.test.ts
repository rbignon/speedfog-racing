import { describe, it, expect } from "vitest";
import { splitRaceName } from "$lib/cast/race-name";

describe("splitRaceName", () => {
  it("splits the organizer's stage - race - mode name into three lines", () => {
    expect(splitRaceName("Semi B - Race 1 - Standard")).toEqual([
      "Semi B",
      "Race 1",
      "Standard",
    ]);
  });

  it("falls back to the whole name on one line when there is nothing to split", () => {
    expect(splitRaceName("Friday Night Speedfog")).toEqual([
      "Friday Night Speedfog",
    ]);
  });

  it("keeps exactly the parts given when there are only two", () => {
    expect(splitRaceName("Semi B - Race 1")).toEqual(["Semi B", "Race 1"]);
  });

  it("drops anything past the third part rather than folding it in", () => {
    expect(splitRaceName("Semi B - Race 1 - Standard - Extra")).toEqual([
      "Semi B",
      "Race 1",
      "Standard",
    ]);
  });

  it("trims stray whitespace around the separator and the parts", () => {
    expect(splitRaceName("Semi B -  Race 1  -   Standard  ")).toEqual([
      "Semi B",
      "Race 1",
      "Standard",
    ]);
  });
});
