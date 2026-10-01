<script lang="ts">
  import type { DebugFlags } from "$lib/api";
  import type { WsParticipant } from "$lib/websocket";
  import { detectionRows } from "$lib/debugFlags";
  import { formatIgt } from "$lib/dag/popupData";

  interface Props {
    detections: Record<string, DebugFlags>;
    participants: WsParticipant[];
    zoneNames?: Map<string, string> | null;
  }

  let { detections, participants, zoneNames = null }: Props = $props();

  let rows = $derived(detectionRows(detections));

  function runnerName(id: string): string {
    const p = participants.find((x) => x.id === id);
    return p ? p.twitch_display_name || p.twitch_username : "Unknown runner";
  }

  function zoneLabel(nodeId: string | null): string {
    if (!nodeId) return "Unknown zone";
    return zoneNames?.get(nodeId) ?? nodeId;
  }
</script>

{#if rows.length > 0}
  <section class="cheat-detections" aria-label="Cheat detections">
    <h3>Cheat detections</h3>
    <ul class="runners">
      {#each rows as row (row.participantId)}
        <li>
          <span class="runner">{runnerName(row.participantId)}</span>
          <ul class="flags">
            {#each row.flags as flag (flag.name)}
              <li>
                <span class="flag">{flag.label}</span>
                <span class="igt">{formatIgt(flag.igtMs)}</span>
                <span class="zone">{zoneLabel(flag.nodeId)}</span>
              </li>
            {/each}
          </ul>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .cheat-detections {
    border-left: 3px solid var(--color-danger);
    padding: 0.75rem 1rem;
    margin-top: 1rem;
  }

  h3 {
    margin: 0 0 0.5rem;
    font-size: var(--font-size-sm);
    color: var(--color-danger);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .runners > li + li {
    margin-top: 0.5rem;
  }

  .runner {
    font-weight: 600;
  }

  .flags li {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    font-size: var(--font-size-sm);
  }

  .igt,
  .zone {
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
  }
</style>
