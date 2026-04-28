import { describe, expect, it } from "vitest";

import {
  computePublicAccess,
  computePublicLockedReason,
  type PublicAccessInputs,
} from "$lib/public-chat-access";

const NOW = new Date("2026-04-28T12:00:00Z");
const REG_OPEN = new Date("2026-04-28T12:30:00Z").toISOString();
const REG_CLOSED = new Date("2026-04-28T11:30:00Z").toISOString();

function inputs(
  overrides: Partial<PublicAccessInputs> = {},
): PublicAccessInputs {
  return {
    raceStatus: "setup",
    registrationClosesAt: null,
    role: null,
    participantStatus: null,
    now: NOW,
    ...overrides,
  };
}

describe("computePublicAccess", () => {
  describe("SETUP", () => {
    it("locked for everyone", () => {
      expect(computePublicAccess(inputs({ raceStatus: "setup" }))).toBe(
        "locked",
      );
      expect(
        computePublicAccess(inputs({ raceStatus: "setup", role: "organizer" })),
      ).toBe("locked");
      expect(
        computePublicAccess(
          inputs({
            raceStatus: "setup",
            role: "participant",
            participantStatus: "registered",
          }),
        ),
      ).toBe("locked");
    });
  });

  describe("RUNNING with late-join open", () => {
    const base: Partial<PublicAccessInputs> = {
      raceStatus: "running",
      registrationClosesAt: REG_OPEN,
    };

    it("locked for anonymous spectator", () => {
      expect(computePublicAccess(inputs(base))).toBe("locked");
    });

    it("locked for active participant", () => {
      expect(
        computePublicAccess(
          inputs({
            ...base,
            role: "participant",
            participantStatus: "playing",
          }),
        ),
      ).toBe("locked");
    });

    it("readable for finished participant", () => {
      expect(
        computePublicAccess(
          inputs({
            ...base,
            role: "participant",
            participantStatus: "finished",
          }),
        ),
      ).toBe("readable");
    });

    it("readable for abandoned participant", () => {
      expect(
        computePublicAccess(
          inputs({
            ...base,
            role: "participant",
            participantStatus: "abandoned",
          }),
        ),
      ).toBe("readable");
    });

    it("readable for organizer/admin/caster", () => {
      for (const role of ["organizer", "admin", "caster"] as const) {
        expect(computePublicAccess(inputs({ ...base, role }))).toBe("readable");
      }
    });
  });

  describe("RUNNING with late-join closed", () => {
    const base: Partial<PublicAccessInputs> = {
      raceStatus: "running",
      registrationClosesAt: REG_CLOSED,
    };

    it("readable for spectator", () => {
      expect(computePublicAccess(inputs(base))).toBe("readable");
    });

    it("locked for active participant", () => {
      expect(
        computePublicAccess(
          inputs({
            ...base,
            role: "participant",
            participantStatus: "playing",
          }),
        ),
      ).toBe("locked");
    });

    it("readable for finished participant", () => {
      expect(
        computePublicAccess(
          inputs({
            ...base,
            role: "participant",
            participantStatus: "finished",
          }),
        ),
      ).toBe("readable");
    });
  });

  describe("RUNNING with no late-join window", () => {
    it("readable for spectator (closed from t=0)", () => {
      expect(
        computePublicAccess(
          inputs({ raceStatus: "running", registrationClosesAt: null }),
        ),
      ).toBe("readable");
    });

    it("locked for active participant", () => {
      expect(
        computePublicAccess(
          inputs({
            raceStatus: "running",
            registrationClosesAt: null,
            role: "participant",
            participantStatus: "playing",
          }),
        ),
      ).toBe("locked");
    });
  });

  describe("FINISHED", () => {
    it("readable for everyone", () => {
      expect(computePublicAccess(inputs({ raceStatus: "finished" }))).toBe(
        "readable",
      );
      expect(
        computePublicAccess(
          inputs({
            raceStatus: "finished",
            role: "participant",
            participantStatus: "finished",
          }),
        ),
      ).toBe("readable");
    });
  });
});

describe("computePublicLockedReason", () => {
  it("setup: registration / start message", () => {
    expect(computePublicLockedReason(inputs({ raceStatus: "setup" }))).toBe(
      "Public chat unlocks after the race starts and registration closes.",
    );
  });

  it("running active participant: finish message", () => {
    const r = computePublicLockedReason(
      inputs({
        raceStatus: "running",
        registrationClosesAt: REG_OPEN,
        role: "participant",
        participantStatus: "playing",
      }),
    );
    expect(r).toBe("Public chat unlocks when you finish.");
  });

  it("running spectator with late join open: late join message", () => {
    const r = computePublicLockedReason(
      inputs({ raceStatus: "running", registrationClosesAt: REG_OPEN }),
    );
    expect(r).toBe("Public chat unlocks when late join closes.");
  });

  it("running active participant after late join closed: finish message", () => {
    const r = computePublicLockedReason(
      inputs({
        raceStatus: "running",
        registrationClosesAt: REG_CLOSED,
        role: "participant",
        participantStatus: "playing",
      }),
    );
    expect(r).toBe("Public chat unlocks when you finish.");
  });

  it("falls back to a generic message for unenumerated cases", () => {
    // Should not normally render in practice; just covers the fallback.
    const r = computePublicLockedReason(
      inputs({ raceStatus: "finished", role: null, participantStatus: null }),
    );
    expect(r).toBe("Public chat is locked.");
  });
});
