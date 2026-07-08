import { describe, expect, it } from "vitest";
import { parseEmphasis } from "$lib/content/emphasis";

describe("parseEmphasis", () => {
  it("returns plain text as a single segment", () => {
    expect(parseEmphasis("no markers here")).toEqual([
      { text: "no markers here", bold: false },
    ]);
  });

  it("returns an empty list for an empty string", () => {
    expect(parseEmphasis("")).toEqual([]);
  });

  it("parses a bold span in the middle", () => {
    expect(parseEmphasis("level **Vigor** first")).toEqual([
      { text: "level ", bold: false },
      { text: "Vigor", bold: true },
      { text: " first", bold: false },
    ]);
  });

  it("parses bold spans at the start and end", () => {
    expect(parseEmphasis("**Torrent** stays out of **Mohg's arena**")).toEqual([
      { text: "Torrent", bold: true },
      { text: " stays out of ", bold: false },
      { text: "Mohg's arena", bold: true },
    ]);
  });

  it("parses multiple bold spans", () => {
    const segments = parseEmphasis("**a** b **c** d");
    expect(segments.filter((s) => s.bold).map((s) => s.text)).toEqual([
      "a",
      "c",
    ]);
  });

  it("renders a dangling marker literally instead of dropping text", () => {
    expect(parseEmphasis("broken **bold text")).toEqual([
      { text: "broken **bold text", bold: false },
    ]);
    expect(parseEmphasis("**closed** then **open")).toEqual([
      { text: "closed", bold: true },
      { text: " then **open", bold: false },
    ]);
  });
});
