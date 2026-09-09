import { describe, expect, it } from "vitest";

import { formatApiErrorDetail } from "$lib/api";

describe("formatApiErrorDetail", () => {
  it("returns a string detail as is", () => {
    expect(formatApiErrorDetail("Race not found")).toBe("Race not found");
  });

  it("formats a Pydantic-shaped validation error list, dropping the leading 'body' loc segment", () => {
    const detail = [
      {
        loc: ["body", "config", "stages", 1, "date"],
        msg: "Input should be a valid datetime with a timezone",
        type: "datetime_from_date_parsing",
      },
    ];
    expect(formatApiErrorDetail(detail)).toBe(
      "config.stages.1.date: Input should be a valid datetime with a timezone",
    );
  });

  it("joins multiple validation errors with '; '", () => {
    const detail = [
      { loc: ["body", "slug"], msg: "Field required", type: "missing" },
      { loc: ["body", "name"], msg: "Field required", type: "missing" },
    ];
    expect(formatApiErrorDetail(detail)).toBe(
      "slug: Field required; name: Field required",
    );
  });

  it("falls back to a generic message for an unexpected shape", () => {
    expect(formatApiErrorDetail({ foo: "bar" })).toBe("Unknown error");
    expect(formatApiErrorDetail(null)).toBe("Unknown error");
    expect(formatApiErrorDetail([])).toBe("Unknown error");
    expect(formatApiErrorDetail(42)).toBe("Unknown error");
  });
});
