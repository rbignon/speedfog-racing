import { describe, expect, it } from "vitest";
import { isNewerVersion, parseVersion } from "$lib/utils/version";

describe("parseVersion", () => {
  it("parses a release version", () => {
    expect(parseVersion("1.17.0")).toEqual([1, 17, 0]);
  });

  it("ignores trailing non-numeric segments", () => {
    expect(parseVersion("1.2.0-rc1")).toEqual([1, 2]);
  });

  it("returns null for garbage", () => {
    expect(parseVersion("abc")).toBeNull();
    expect(parseVersion("")).toBeNull();
  });
});

describe("isNewerVersion", () => {
  it("detects a newer patch", () => {
    expect(isNewerVersion("1.17.1", "1.17.0")).toBe(true);
  });

  it("detects a newer minor and major", () => {
    expect(isNewerVersion("1.18.0", "1.17.9")).toBe(true);
    expect(isNewerVersion("2.0.0", "1.99.0")).toBe(true);
  });

  it("is false for equal versions", () => {
    expect(isNewerVersion("1.17.0", "1.17.0")).toBe(false);
  });

  it("is false for older versions", () => {
    expect(isNewerVersion("1.16.0", "1.17.0")).toBe(false);
  });

  it("treats missing segments as zero", () => {
    expect(isNewerVersion("1.17", "1.17.0")).toBe(false);
    expect(isNewerVersion("1.17.1", "1.17")).toBe(true);
  });

  it("is false when either side is unparsable", () => {
    expect(isNewerVersion("garbage", "1.17.0")).toBe(false);
    expect(isNewerVersion("1.18.0", "garbage")).toBe(false);
  });
});
