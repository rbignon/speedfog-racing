<script lang="ts">
  import { fetchZoneDetail, type ZoneDetailResponse } from "$lib/api";
  import EmphasisText from "$lib/components/EmphasisText.svelte";
  import VideoEmbed from "$lib/components/VideoEmbed.svelte";
  import { skipsForZones, zoneTipsForZones } from "$lib/content/zones";

  interface Props {
    nodeId: string;
    displayName?: string | null;
    /** Exact per-seed zone composition, when opened from the race DAG popup. */
    zones?: string[] | null;
    onClose: () => void;
  }

  let { nodeId, displayName = null, zones = null, onClose }: Props = $props();

  let detail = $state<ZoneDetailResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  // Keyed on nodeId so the sheet can be retargeted (user clicks another zone
  // row) without unmounting. The cleanup flips `cancelled` for the in-flight
  // request from the previous nodeId, so an out-of-order response can never
  // overwrite state for the zone the user is now looking at.
  $effect(() => {
    const targetNodeId = nodeId;
    let cancelled = false;
    loading = true;
    error = null;
    detail = null;

    fetchZoneDetail(targetNodeId)
      .then((result) => {
        if (cancelled) return;
        detail = result;
      })
      .catch((e) => {
        if (cancelled) return;
        error = e instanceof Error ? e.message : "Failed to load zone stats.";
      })
      .finally(() => {
        if (cancelled) return;
        loading = false;
      });

    return () => {
      cancelled = true;
    };
  });

  let headerName = $derived(detail?.display_name ?? displayName ?? nodeId);
  let headerType = $derived(detail?.type ?? null);
  let hasStats = $derived(
    detail !== null && detail.visits > 0 && detail.avg_time_ms !== null,
  );

  // The prop carries the exact cluster variant the player is looking at
  // (from the DAG popup); when opened from the zone index, fall back to
  // the detail response's own composition once it loads.
  let effectiveZones = $derived(zones ?? detail?.zones ?? []);
  let skips = $derived(skipsForZones(effectiveZones));
  let tips = $derived(zoneTipsForZones(effectiveZones));

  function typeBadgeClass(type: string): string {
    if (type === "legacy_dungeon") return "type-badge-legacy";
    return "type-badge-mini";
  }

  function typeLabel(type: string): string {
    if (type === "legacy_dungeon") return "Legacy";
    return "Minor";
  }

  function formatTime(ms: number): string {
    const totalSeconds = Math.round(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }
</script>

<div class="zone-sheet">
  <div class="sheet-header">
    <div class="header-text">
      <h2>{headerName}</h2>
      {#if headerType}
        <span class="type-badge {typeBadgeClass(headerType)}"
          >{typeLabel(headerType)}</span
        >
      {/if}
    </div>
    <button class="close-btn" onclick={onClose} aria-label="Close"
      >&times;</button
    >
  </div>

  <div class="stats-strip">
    {#if loading}
      <p class="status-text">Loading...</p>
    {:else if error}
      <p class="status-text error-text">{error}</p>
    {:else if !hasStats}
      <p class="status-text">No recorded runs in the last 90 days</p>
    {:else if detail && detail.avg_time_ms !== null}
      <div class="stats-grid">
        <div class="stat-item">
          <span class="label">Avg. Time</span>
          <span class="value">{formatTime(detail.avg_time_ms)}</span>
        </div>
        <div class="stat-item">
          <span class="label">Avg. Deaths</span>
          <span class="value">{detail.avg_deaths_per_visit.toFixed(1)}</span>
        </div>
        <div class="stat-item">
          <span class="label">Backtracks / Race</span>
          <!-- Avg backtracks per race, not a proportion: same "x"
               multiplier convention as ZonesTab's panel. -->
          <span class="value">{detail.backtrack_rate.toFixed(1)}x</span>
        </div>
        <div class="stat-item">
          <span class="label">Visits</span>
          <span class="value">{detail.visits}</span>
        </div>
      </div>
    {/if}
  </div>

  <div class="section">
    <h3>Skips</h3>
    {#if skips.length === 0}
      <p class="empty">
        No skips documented yet. Found one? Tell us on
        <a
          href="https://discord.gg/Qmw67J3mR9"
          target="_blank"
          rel="noopener noreferrer">Discord</a
        >.
      </p>
    {:else}
      <div class="skip-list">
        {#each skips as skip (skip.id)}
          <div class="skip-card">
            <div class="skip-header">
              <h4>{skip.title}</h4>
              <div class="badges">
                {#if skip.difficulty}
                  <span class="difficulty-badge">{skip.difficulty}</span>
                {/if}
              </div>
            </div>
            {#if skip.short.trim().length > 0}
              <p class="skip-short"><EmphasisText text={skip.short} /></p>
            {/if}
            {#if skip.credit}
              <p class="credit">video by {skip.credit}</p>
            {/if}
            {#if skip.video}
              <VideoEmbed
                youtubeId={skip.video.youtubeId}
                title={skip.title}
                start={skip.video.start}
              />
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>

  {#if tips.length > 0}
    <div class="section">
      <h3>Zone Tips</h3>
      <ul class="tips-list">
        {#each tips as tip (tip.id)}
          <li>
            <strong>{tip.title}</strong>: <EmphasisText text={tip.short} />
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <div class="sheet-footer">
    <a
      href="https://discord.gg/Qmw67J3mR9"
      target="_blank"
      rel="noopener noreferrer">Suggest a skip on Discord</a
    >
  </div>
</div>

<style>
  .zone-sheet {
    height: 100%;
    overflow-y: auto;
    box-sizing: border-box;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .sheet-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .header-text {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .header-text h2 {
    margin: 0;
    color: var(--color-gold);
    font-size: var(--font-size-lg);
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    flex-shrink: 0;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .type-badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.4rem;
    border-radius: var(--radius-sm);
  }

  .type-badge-legacy {
    background: rgba(200, 164, 78, 0.2);
    color: var(--color-gold);
  }

  .type-badge-mini {
    background: rgba(107, 114, 128, 0.2);
    color: var(--color-text-secondary);
  }

  .stats-strip {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.25rem;
  }

  .status-text {
    margin: 0;
    color: var(--color-text-disabled);
    font-style: italic;
    font-size: var(--font-size-sm);
  }

  .error-text {
    color: var(--color-danger);
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: 1rem;
  }

  .stat-item {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .stat-item .label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  .stat-item .value {
    font-weight: 600;
    font-size: var(--font-size-lg);
    font-variant-numeric: tabular-nums;
  }

  .section h3 {
    margin: 0 0 0.75rem 0;
    font-size: var(--font-size-base);
    color: var(--color-text);
  }

  .empty {
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
    margin: 0;
  }

  .skip-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .skip-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 0.85rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .skip-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .skip-header h4 {
    margin: 0;
    font-size: var(--font-size-base);
    font-weight: 600;
  }

  .badges {
    display: flex;
    gap: 0.35rem;
    flex-shrink: 0;
  }

  .difficulty-badge {
    background: rgba(107, 114, 128, 0.2);
    color: var(--color-text-secondary);
  }

  .skip-short {
    margin: 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    line-height: 1.5;
  }

  .credit {
    margin: 0;
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .tips-list {
    margin: 0;
    padding-left: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .tips-list li {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    line-height: 1.5;
  }

  .sheet-footer {
    margin-top: auto;
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
    text-align: center;
    font-size: var(--font-size-sm);
  }
</style>
