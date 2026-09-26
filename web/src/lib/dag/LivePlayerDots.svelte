<script lang="ts">
  import { untrack } from "svelte";
  import { SKULL_PATH } from "$lib/components/SkullIcon.svelte";
  import type { WsParticipant } from "$lib/websocket";
  import type { PositionedNode } from "./types";
  import {
    PADDING,
    PLAYER_COLORS,
    RACER_DOT_RADIUS,
    LIVE_ORBIT_RADIUS,
    LIVE_ORBIT_PERIOD_MS,
    LIVE_SKULL_ANIM_MS,
    LIVE_SKULL_PEAK_SCALE,
    LIVE_SKULL_SIZE,
    LIVE_FINISHED_X_OFFSET,
    LIVE_START_X_OFFSET,
    LIVE_TAG_RING,
    LIVE_TAG_GLOW_SPREAD,
    LIVE_TAG_GLOW_BLUR,
    LIVE_TAG_LINE_LENGTH,
    LIVE_TAG_LINE_WIDTH,
    LIVE_TAG_NAME_GAP,
    LIVE_TAG_FONT_SIZE,
    LIVE_TAG_TIER_GAP,
    LIVE_TAG_MAX_TIERS,
    LIVE_TAG_SHADOW_OFFSET,
    LIVE_TAG_SHADOW_BLUR,
  } from "./constants";
  import {
    estimateNameWidth,
    placeTags,
    spreadColocated,
    type TagPoint,
    type TagView,
  } from "./tags";

  interface Props {
    participants: WsParticipant[];
    nodeMap: Map<string, PositionedNode>;
    raceStatus?: string;
    /** Show dots in pre-race position (aligned left of start) */
    preRace?: boolean;
    /** Draw each runner as a tag instead of an orbiting dot: a still dot, a
     * straight connector and the runner's name above or below it, placed
     * so names don't cover each other (see `placeTags`). Off by default:
     * the strip-sized embeds (the race page, the plain /dag overlays,
     * training) have no room for names. Drawn in the SVG rather than as an
     * HTML overlay so tags ride the viewport's pan and zoom for free. */
    playerTags?: boolean;
    /** The part of the map on screen, in graph units: tags stay inside it,
     * and a runner whose spot is outside it gets none. Defaults to the
     * nodes' own extent plus the layout's padding, i.e. the whole map. */
    view?: TagView;
  }

  let {
    participants,
    nodeMap,
    raceStatus,
    preRace = false,
    playerTags = false,
    view,
  }: Props = $props();

  // Wall-clock elapsed time for orbit animation
  let elapsed = $state(0);
  let frameId: number;

  $effect(() => {
    const start = performance.now();
    function tick() {
      elapsed = performance.now() - start;
      frameId = requestAnimationFrame(tick);
    }
    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  });

  // Find start node (type === 'start') for pre-race positioning
  let startNode = $derived.by(() => {
    for (const node of nodeMap.values()) {
      if (node.type === "start") return node;
    }
    return null;
  });

  // Find final boss node for finished positioning
  let finalBossNode = $derived.by(() => {
    for (const node of nodeMap.values()) {
      if (node.type === "final_boss") return node;
    }
    return null;
  });

  // Track previous death counts to detect new deaths (plain Map, not reactive)
  const prevDeaths = new Map<string, number>();
  interface SkullAnim {
    id: string;
    participantId: string;
    nodeId: string;
    startTime: number;
  }
  let skulls = $state<SkullAnim[]>([]);

  $effect(() => {
    const now = performance.now();
    const newSkulls: SkullAnim[] = [];
    for (const p of participants) {
      const prev = prevDeaths.get(p.id) ?? 0;
      if (p.death_count > prev && p.current_zone) {
        for (let i = 0; i < p.death_count - prev; i++) {
          newSkulls.push({
            id: `${p.id}-${now}-${i}`,
            participantId: p.id,
            nodeId: p.current_zone,
            startTime: now,
          });
        }
      }
      prevDeaths.set(p.id, p.death_count);
    }
    if (newSkulls.length > 0) {
      const existing = untrack(() => skulls);
      skulls = [
        ...existing.filter(
          (s) => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS,
        ),
        ...newSkulls,
      ];
    }
  });

  // Clean up expired skulls periodically
  $effect(() => {
    // Re-run when elapsed changes (every frame)
    void elapsed;
    const current = untrack(() => skulls);
    if (current.length === 0) return;
    skulls = current.filter(
      (s) => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS,
    );
  });

  // Pre-compute finished players list (avoids re-filtering every frame)
  let finishedPlayers = $derived(
    participants.filter((p) => p.status === "finished"),
  );

  interface DotPosition {
    participantId: string;
    x: number;
    y: number;
    color: string;
    displayName: string;
    opacity: number;
  }

  let dots: DotPosition[] = $derived.by(() => {
    // Reads `elapsed` below, so this reruns every frame: skip it entirely
    // when tags are drawn instead.
    if (playerTags) return [];
    const result: DotPosition[] = [];
    const playingAtNode = new Map<string, number>();

    for (let i = 0; i < participants.length; i++) {
      const p = participants[i];
      const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
      const displayName = p.twitch_display_name || p.twitch_username;

      if (preRace && startNode) {
        // Pre-race: align left of start node
        const spacing = RACER_DOT_RADIUS * 2;
        const totalSpread = (participants.length - 1) * spacing;
        const yOffset = -totalSpread / 2 + i * spacing;
        result.push({
          participantId: p.id,
          x: startNode.x + LIVE_START_X_OFFSET,
          y: startNode.y + yOffset,
          color,
          displayName,
          opacity: 1,
        });
        continue;
      }

      if (p.status === "finished" && finalBossNode) {
        // Finished: align right of final boss
        const idx = finishedPlayers.indexOf(p);
        const spacing = RACER_DOT_RADIUS * 2;
        const totalSpread = (finishedPlayers.length - 1) * spacing;
        const yOffset = -totalSpread / 2 + idx * spacing;
        result.push({
          participantId: p.id,
          x: finalBossNode.x + LIVE_FINISHED_X_OFFSET,
          y: finalBossNode.y + yOffset,
          color,
          displayName,
          opacity: 1,
        });
        continue;
      }

      if (p.status === "abandoned" && p.current_zone) {
        const node = nodeMap.get(p.current_zone);
        if (node) {
          result.push({
            participantId: p.id,
            x: node.x,
            y: node.y,
            color,
            displayName,
            opacity: 0.35,
          });
        }
        continue;
      }

      if ((p.status === "playing" || p.status === "ready") && p.current_zone) {
        const node = nodeMap.get(p.current_zone);
        if (node) {
          // Count how many players are at this node for phase offset
          const countAtNode = playingAtNode.get(p.current_zone) ?? 0;
          playingAtNode.set(p.current_zone, countAtNode + 1);

          const phaseOffset =
            (countAtNode / Math.max(participants.length, 1)) * Math.PI * 2;
          const angle =
            phaseOffset + (elapsed / LIVE_ORBIT_PERIOD_MS) * Math.PI * 2;
          result.push({
            participantId: p.id,
            x: node.x + Math.cos(angle) * LIVE_ORBIT_RADIUS,
            y: node.y + Math.sin(angle) * LIVE_ORBIT_RADIUS,
            color,
            displayName,
            opacity: 1,
          });
        }
        continue;
      }
    }
    return result;
  });

  // --- tags ---------------------------------------------------------------

  // Rings touch with a hair between them when runners share a spot.
  const TAG_SPACING = 2 * (RACER_DOT_RADIUS + LIVE_TAG_RING) + 1;
  // The box the text-before/after-edge baselines align is the font's
  // ascent plus descent, about 1.2em, not the bare em.
  const TAG_NAME_HEIGHT = LIVE_TAG_FONT_SIZE * 1.2;
  const TAG_METRICS = {
    dotRadius: RACER_DOT_RADIUS + LIVE_TAG_RING,
    reach: RACER_DOT_RADIUS + LIVE_TAG_LINE_LENGTH + LIVE_TAG_NAME_GAP,
    nameHeight: TAG_NAME_HEIGHT,
    tierStep: TAG_NAME_HEIGHT + LIVE_TAG_TIER_GAP,
    maxTiers: LIVE_TAG_MAX_TIERS,
  };

  let tagView: TagView = $derived.by(() => {
    if (view) return view;
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    for (const node of nodeMap.values()) {
      left = Math.min(left, node.x - PADDING);
      right = Math.max(right, node.x + PADDING);
      top = Math.min(top, node.y - PADDING);
      bottom = Math.max(bottom, node.y + PADDING);
    }
    return { left, right, top, bottom };
  });

  interface TagPosition {
    participantId: string;
    x: number;
    y: number;
    color: string;
    displayName: string;
    opacity: number;
    dir: -1 | 1;
    reach: number;
    nameX: number;
  }

  let tags: TagPosition[] = $derived.by(() => {
    if (!playerTags) return [];
    const points: (TagPoint & {
      spotX: number;
      color: string;
      displayName: string;
      opacity: number;
      lean: -1 | 1;
    })[] = [];
    // Same spots as the orbiting dots, minus the orbit. Pre-race, the field
    // gathers on the start node itself, as it does once the race starts:
    // the viewport shows little to its left. The finish group extends past
    // the final node, so a crowd doesn't sit on it.
    const finishShift = ((finishedPlayers.length - 1) / 2) * TAG_SPACING;
    for (const p of participants) {
      let spot: {
        key: string;
        x: number;
        y: number;
        spotX: number;
        opacity: number;
      };
      if (preRace && startNode) {
        spot = {
          key: "start",
          x: startNode.x,
          spotX: startNode.x,
          y: startNode.y,
          opacity: 1,
        };
      } else if (p.status === "finished" && finalBossNode) {
        spot = {
          key: "finish",
          x: finalBossNode.x + LIVE_FINISHED_X_OFFSET + finishShift,
          spotX: finalBossNode.x,
          y: finalBossNode.y,
          opacity: 1,
        };
      } else if (
        (p.status === "abandoned" ||
          p.status === "playing" ||
          p.status === "ready") &&
        p.current_zone
      ) {
        const node = nodeMap.get(p.current_zone);
        if (!node) continue;
        spot = {
          key: node.id,
          x: node.x,
          spotX: node.x,
          y: node.y,
          opacity: p.status === "abandoned" ? 0.35 : 1,
        };
      } else {
        continue;
      }
      points.push({
        id: p.id,
        key: spot.key,
        x: spot.x,
        y: spot.y,
        spotX: spot.spotX,
        color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
        displayName: p.twitch_display_name || p.twitch_username,
        opacity: spot.opacity,
        // Stable per runner, so a tag on the middle row keeps its side.
        lean: p.color_index % 2 === 0 ? -1 : 1,
      });
    }

    const spread = spreadColocated(points, TAG_SPACING);
    const anchors = points.map((pt) => ({
      id: pt.id,
      ...spread.get(pt.id)!,
      width: estimateNameWidth(pt.displayName, LIVE_TAG_FONT_SIZE),
      spotX: pt.spotX,
      lean: pt.lean,
    }));
    const placements = placeTags(anchors, tagView, TAG_METRICS);
    return points.flatMap((pt, i) => {
      const placement = placements.get(pt.id);
      if (!placement) return [];
      return [
        {
          participantId: pt.id,
          x: anchors[i].x,
          y: anchors[i].y,
          color: pt.color,
          displayName: pt.displayName,
          opacity: pt.opacity,
          ...placement,
        },
      ];
    });
  });

  function skullScale(progress: number): number {
    if (progress < 0.3) return (progress / 0.3) * LIVE_SKULL_PEAK_SCALE;
    if (progress < 0.5) {
      const overshoot = LIVE_SKULL_PEAK_SCALE - 1.0;
      return LIVE_SKULL_PEAK_SCALE - ((progress - 0.3) / 0.2) * overshoot;
    }
    return 1.0;
  }

  function skullOpacity(progress: number): number {
    if (progress < 0.5) return 1;
    return 1 - (progress - 0.5) / 0.5;
  }
</script>

{#if playerTags}
  <defs>
    <filter id="player-tag-glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation={LIVE_TAG_GLOW_BLUR} />
    </filter>
    <filter id="player-tag-shadow" x="-20%" y="-50%" width="140%" height="200%">
      <feDropShadow
        dx="0"
        dy={LIVE_TAG_SHADOW_OFFSET}
        stdDeviation={LIVE_TAG_SHADOW_BLUR}
        flood-color="#080d13"
        flood-opacity="0.95"
      />
    </filter>
  </defs>
  <!-- Three passes, so every name sits above every connector and dot. -->
  {#each tags as tag (tag.participantId)}
    <line
      x1={tag.x}
      y1={tag.y + tag.dir * RACER_DOT_RADIUS}
      x2={tag.x}
      y2={tag.y + tag.dir * (tag.reach - LIVE_TAG_NAME_GAP)}
      stroke={tag.color}
      stroke-width={LIVE_TAG_LINE_WIDTH}
      opacity={tag.opacity * 0.5}
      class="tag-line"
    />
  {/each}
  {#each tags as tag (tag.participantId)}
    <g opacity={tag.opacity} class="tag-dot">
      <circle
        cx={tag.x}
        cy={tag.y}
        r={RACER_DOT_RADIUS + LIVE_TAG_GLOW_SPREAD}
        fill={tag.color}
        filter="url(#player-tag-glow)"
      />
      <circle
        cx={tag.x}
        cy={tag.y}
        r={RACER_DOT_RADIUS + LIVE_TAG_RING}
        fill="var(--color-bg, #0f1923)"
        fill-opacity="0.95"
      />
      <circle cx={tag.x} cy={tag.y} r={RACER_DOT_RADIUS} fill={tag.color}>
        <title>{tag.displayName}</title>
      </circle>
    </g>
  {/each}
  {#each tags as tag (tag.participantId)}
    <text
      x={tag.nameX}
      y={tag.y + tag.dir * tag.reach}
      text-anchor="middle"
      dominant-baseline={tag.dir < 0 ? "text-after-edge" : "text-before-edge"}
      font-size={LIVE_TAG_FONT_SIZE}
      fill={tag.color}
      opacity={tag.opacity}
      filter="url(#player-tag-shadow)"
      class="tag-name">{tag.displayName}</text
    >
  {/each}
{:else}
  <!-- Player dots -->
  {#each dots as dot (dot.participantId)}
    <circle
      cx={dot.x}
      cy={dot.y}
      r={RACER_DOT_RADIUS}
      fill={dot.color}
      opacity={dot.opacity}
      filter={dot.opacity < 1 ? undefined : "url(#player-glow)"}
      class="live-dot"
    >
      <title>{dot.displayName}</title>
    </circle>
  {/each}
{/if}

<!-- Skull animations -->
{#each skulls as skull (skull.id)}
  {@const pos = nodeMap.get(skull.nodeId)}
  {@const progress = (performance.now() - skull.startTime) / LIVE_SKULL_ANIM_MS}
  {#if pos && progress < 1}
    {@const s = (LIVE_SKULL_SIZE / 24) * skullScale(progress)}
    <path
      d={SKULL_PATH}
      fill="var(--color-danger)"
      fill-rule="evenodd"
      transform="translate({pos.x - 12 * s} {pos.y - 12 * s}) scale({s})"
      opacity={skullOpacity(progress)}
      class="skull-anim"
    />
  {/if}
{/each}

<style>
  .live-dot {
    pointer-events: none;
  }
  .skull-anim {
    pointer-events: none;
  }
  .tag-line,
  .tag-dot {
    pointer-events: none;
  }

  .tag-name {
    pointer-events: none;
    user-select: none;
    font-family: var(--font-display);
    font-weight: 600;
    letter-spacing: 0.02em;
  }
</style>
