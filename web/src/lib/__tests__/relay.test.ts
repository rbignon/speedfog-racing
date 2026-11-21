import { describe, expect, it } from "vitest";

import { relayCap, relayCapSentence } from "$lib/relay";

describe("relayCap", () => {
  it("computes ceil(layers / members) + 1 like the server", () => {
    expect([relayCap(30, 3), relayCap(12, 3), relayCap(13, 3)]).toEqual([
      11, 5, 6,
    ]);
  });

  it("counts a team with no active member as one", () => {
    expect(relayCap(12, 0)).toBe(13);
  });
});

describe("relayCapSentence", () => {
  it("writes the cap for the pool's zone count and the team size", () => {
    expect(relayCapSentence(30, 3)).toBe(
      "30 zones, teams of 3: 11 zones max per runner.",
    );
  });

  it("says nothing without a zone count", () => {
    expect([
      relayCapSentence(null, 3),
      relayCapSentence(undefined, 3),
      relayCapSentence(0, 3),
    ]).toEqual([null, null, null]);
  });
});
