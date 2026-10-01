import { describe, expect, it } from "vitest";

import { isFrogTitle, isOutOfRace, statusLabel } from "$lib/format";

describe("isFrogTitle", () => {
  it("matches the substring regardless of case", () => {
    expect(isFrogTitle("Frog race")).toBe(true);
    expect(isFrogTitle("THE FROG CUP")).toBe(true);
  });

  it("matches when frog is part of a larger word", () => {
    expect(isFrogTitle("Froggers only")).toBe(true);
    expect(isFrogTitle("bullfrog sprint")).toBe(true);
  });

  it("does not match unrelated titles", () => {
    expect(isFrogTitle("Sunday racing")).toBe(false);
    expect(isFrogTitle("from the start")).toBe(false);
  });

  it("does not match an empty title", () => {
    expect(isFrogTitle("")).toBe(false);
  });
});

describe("disqualified status", () => {
  it("labels a disqualification", () => {
    expect(statusLabel("disqualified")).toBe("Disqualified");
  });

  it("counts abandoned and disqualified runners as out of the race", () => {
    expect(isOutOfRace("abandoned")).toBe(true);
    expect(isOutOfRace("disqualified")).toBe(true);
    expect(isOutOfRace("finished")).toBe(false);
    expect(isOutOfRace("playing")).toBe(false);
  });
});
