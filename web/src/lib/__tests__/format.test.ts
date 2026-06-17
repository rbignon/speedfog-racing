import { describe, expect, it } from "vitest";

import { isFrogTitle } from "$lib/format";

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
