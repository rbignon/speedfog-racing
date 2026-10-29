import { describe, expect, it } from "vitest";
import { isHttpError } from "@sveltejs/kit";
import { load } from "../../routes/speedrun/seed/[seed]/+page";

// The seed endpoint answering `status` (a FastAPI error body).
async function loadAnswering(status: number, detail: string): Promise<unknown> {
  const fetch = async () => Response.json({ detail }, { status });
  try {
    await load({
      params: { seed: "363096" },
      url: new URL("http://localhost/speedrun/seed/363096"),
      fetch,
    } as never);
  } catch (e) {
    return e;
  }
  throw new Error("load did not fail");
}

describe("seed page load: a lookup without a page", () => {
  it("shows the not-found page for an unknown seed", async () => {
    const e = await loadAnswering(404, "Unknown seed");

    expect(isHttpError(e, 404) && e.body.message).toBe("Seed not found");
  });

  it("asks for more of the ID when a prefix matches several seeds", async () => {
    const e = await loadAnswering(409, "Ambiguous seed ID");

    expect(isHttpError(e, 404) && e.body.message).toBe(
      "Several seeds start with 363096. Use more of the seed ID.",
    );
  });

  it("does not call a server failure a missing seed", async () => {
    const e = await loadAnswering(500, "Internal Server Error");

    expect(isHttpError(e)).toBe(false);
    expect((e as Error).message).toBe("Internal Server Error");
  });
});
