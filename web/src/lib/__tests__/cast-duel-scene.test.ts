import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/svelte";
import { raceStore } from "$lib/stores/race.svelte";
import { parseCastParams } from "$lib/cast/params";
import type { WsParticipant } from "$lib/websocket";

vi.mock("$app/state", () => ({
  page: {
    url: new URL("http://localhost/overlay/cast/race/r-1/duel?cams=2"),
  },
}));

// The cards' weapon line loads its catalogue over the network on mount.
vi.mock("$lib/stores/weaponsCatalogue.svelte", () => ({
  loadCatalogue: () => Promise.resolve(),
  isCatalogueReady: () => true,
  getWeaponName: (id: number) => `Weapon ${id}`,
}));

import DuelScene from "../../routes/overlay/cast/race/[id]/duel/+page.svelte";

function runner(i: number): WsParticipant {
  return {
    id: `p-${i}`,
    twitch_username: `runner${i}`,
    twitch_display_name: `Runner${i}`,
    status: "playing",
    current_zone: null,
    current_layer: 3,
    igt_ms: 90_000,
    death_count: 0,
    color_index: i,
    mod_connected: true,
    zone_history: null,
    equipped_badge_id: null,
    equipped_name_template_id: null,
  } as unknown as WsParticipant;
}

function renderScene(field: number) {
  raceStore.participants = Array.from({ length: field }, (_, i) => runner(i));
  return render(DuelScene, {
    props: {
      data: {
        race: {
          id: "r-1",
          name: "Group C - Race 3 - Standard",
          status: "running",
          started_at: new Date(Date.now() - 60_000).toISOString(),
          participants: [],
          seed_total_layers: 10,
        },
        castParams: parseCastParams(new URL("http://localhost/?cams=2")),
        partnerName: null,
      },
    } as never,
  });
}

afterEach(() => {
  raceStore.participants = [];
});

// The cards and the versus block follow the two seated runners only; the
// standings are what keeps the rest of the field, and each runner's gap to
// the leader, on screen.
describe("cast duel scene: standings", () => {
  it("lists a four-runner group whole, the two runners off screen included", () => {
    const { container } = renderScene(4);
    const names = [...container.querySelectorAll(".clb .lrow .nm")].map(
      (n) => n.textContent,
    );
    expect(names).toEqual(["Runner0", "Runner1", "Runner2", "Runner3"]);
    expect(container.querySelector(".clb .lrow.more")).toBeNull();
  });
});
