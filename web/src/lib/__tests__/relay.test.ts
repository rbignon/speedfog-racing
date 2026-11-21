import { describe, expect, it } from "vitest";

import { isValidRelayTeamSize, relayCap, relayCapSentence } from "$lib/relay";

describe("relayCap", () => {
  it("computes ceil(layers / members) + 1 like the server", () => {
    expect([
      relayCap(30, 3),
      relayCap(12, 3),
      relayCap(13, 3),
      relayCap(30, 2),
      relayCap(30, 6),
    ]).toEqual([11, 5, 6, 16, 6]);
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

describe("isValidRelayTeamSize", () => {
  it("accepts integers from 2 to 6 only", () => {
    const accepted = [null, 1, 2, 6, 7, 2.5, 0].map(isValidRelayTeamSize);
    expect(accepted).toEqual([false, false, true, true, false, false, false]);
  });

  it("gives no cap sentence for an invalid size", () => {
    expect(relayCapSentence(30, 1)).toBeNull();
    expect(relayCapSentence(30, null)).toBeNull();
  });
});
