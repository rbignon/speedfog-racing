<script lang="ts">
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";

  interface Props {
    participants: WsParticipant[];
    totalLayers?: number | null;
    mode?: "running" | "finished";
    lines?: number | null;
    deathless?: boolean;
  }

  let {
    participants,
    totalLayers = null,
    mode = "running",
    lines = null,
    deathless = false,
  }: Props = $props();

  let visibleParticipants = $derived(
    lines != null && lines > 0 ? participants.slice(0, lines) : participants,
  );

  function playerColor(p: WsParticipant): string {
    return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
  }

  function formatIgt(ms: number): string {
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }

  function displayName(p: WsParticipant): string {
    return p.twitch_display_name || p.twitch_username;
  }

  function templateFor(p: WsParticipant) {
    const id = p.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  }

  function nameStyleFor(p: WsParticipant): string {
    const t = templateFor(p);
    const parts: string[] = [];
    if (t?.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        "padding-inline-end: 0.1em;",
      );
    } else if (t?.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t?.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  }

  function backgroundStyleFor(p: WsParticipant): string {
    const t = templateFor(p);
    return t?.background_css ? `background: ${t.background_css};` : "";
  }
</script>

<ol class="overlay-leaderboard">
  {#each visibleParticipants as participant, index (participant.id)}
    {@const color = playerColor(participant)}
    {@const badge = rewards.lookupBadge(participant.equipped_badge_id)}
    <li class="row" style={backgroundStyleFor(participant)}>
      <span class="rank">{index + 1}</span>
      <span class="dot" style="background: {color};"></span>
      <span class="name" style={nameStyleFor(participant)}
        >{displayName(participant)}{#if badge}<img
            src="/badges/{badge.icon_filename}"
            alt={badge.name}
            title={badge.name}
            class="participant-badge"
          />{/if}</span
      >
      <span class="stats">
        {#if participant.status === "playing"}
          <span class="layer"
            >{Math.min(
              participant.current_layer + 1,
              totalLayers || Infinity,
            )}{totalLayers ? `/${totalLayers}` : ""}</span
          >
          {#if participant.gap_ms != null}
            <span
              class="gap"
              class:ahead={participant.gap_ms < 0}
              class:behind={participant.gap_ms > 0}
              >{formatGap(participant.gap_ms)}</span
            >
          {/if}
          {#if participant.death_count > 0}
            <span class="deaths">{participant.death_count}</span>
          {/if}
        {:else if participant.status === "finished"}
          <span class="igt finished">{formatIgt(participant.igt_ms)}</span>
          {#if participant.gap_ms != null}
            <span
              class="gap"
              class:ahead={participant.gap_ms < 0}
              class:behind={participant.gap_ms > 0}
              >{formatGap(participant.gap_ms)}</span
            >
          {/if}
          {#if participant.death_count > 0}
            <span class="deaths">{participant.death_count}</span>
          {/if}
        {:else if participant.status === "abandoned"}
          <span class="dnf"
            >{deathless && participant.death_count > 0 ? "DEAD" : "DNF"}</span
          >
        {:else}
          <span class="waiting">{participant.status}</span>
        {/if}
      </span>
    </li>
  {/each}
</ol>

<style>
  .overlay-leaderboard {
    list-style: none;
    padding: 0.5rem;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    font-family: var(--font-mono);
  }

  .row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: white;
    font-size: 1rem;
    text-shadow:
      0 2px 4px rgba(0, 0, 0, 0.9),
      0 0 8px rgba(0, 0, 0, 0.7);
  }

  .rank {
    width: 1.5ch;
    text-align: right;
    flex-shrink: 0;
    opacity: 0.7;
    margin-right: 0.5em;
  }

  .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    flex-shrink: 0;
    box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
  }

  .name {
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
  }

  .stats {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }

  .layer {
    font-weight: 600;
    opacity: 0.9;
  }

  .igt {
    opacity: 0.8;
  }

  .igt.finished {
    color: #4ade80;
    opacity: 1;
  }

  .deaths {
    color: #f87171;
    opacity: 0.9;
  }

  .deaths::before {
    content: "\1F480";
    margin-right: 0.15em;
  }

  .gap.ahead {
    color: #4ade80;
  }

  .gap.behind {
    color: #f87171;
  }

  .dnf {
    color: #9ca3af;
    font-style: italic;
  }

  .waiting {
    text-transform: capitalize;
    opacity: 0.6;
  }

  .participant-badge {
    width: 18px;
    height: 18px;
    vertical-align: middle;
    margin-left: 0.25rem;
    flex-shrink: 0;
  }
</style>
