<script lang="ts">
  import type { ActivityItem } from "$lib/api";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";

  interface Props {
    items: ActivityItem[];
    formatDate: (iso: string) => string;
  }

  let { items, formatDate }: Props = $props();

  function linkFor(item: ActivityItem): string {
    if (item.type === "training") return `/training/${item.session_id}`;
    if (item.type === "daily_participant") return `/daily/${item.daily_date}`;
    return `/race/${item.race_id}`;
  }

  function titleFor(item: ActivityItem): string {
    if (item.type === "training" || item.type === "daily_participant")
      return item.pool_display_name || formatPoolName(item.pool_name);
    return item.race_name;
  }

  /* Category markers reuse the network vocabulary: station ring = race,
   * boss diamond = daily, terminal square = solo. */
  function kindFor(item: ActivityItem): { mark: string; label: string } {
    if (item.type === "training") return { mark: "solo", label: "Solo" };
    if (item.type === "daily_participant")
      return { mark: "daily", label: "Daily" };
    return { mark: "race", label: "Race" };
  }

  function placeLabel(placement: number): string {
    if (placement % 100 >= 11 && placement % 100 <= 13) return `${placement}th`;
    if (placement % 10 === 1) return `${placement}st`;
    if (placement % 10 === 2) return `${placement}nd`;
    if (placement % 10 === 3) return `${placement}rd`;
    return `${placement}th`;
  }
</script>

<div class="act-list">
  {#each items as item (item.type + "-" + ("race_id" in item ? item.race_id : item.session_id) + "-" + item.date)}
    {@const kind = kindFor(item)}
    <a href={linkFor(item)} class="act-row">
      <span class="act-kind">
        <span class="mark mark-{kind.mark}" aria-hidden="true"></span>
        {kind.label}
      </span>
      <span class="act-main">
        <span class="t">
          <span class="title">{titleFor(item)}</span>
        </span>
        <span class="m">
          {#if item.type === "race_participant" || item.type === "daily_participant"}
            {#if item.type === "race_participant" && item.is_organizer}
              <span>Organized</span>
            {/if}
            <!-- item.status is the RACE status: a finished run inside a
                 still-running race (every daily for 24h) already carries its
                 placement, so the placement always wins over the state. -->
            {#if item.placement}
              <span class="place" class:first={item.placement === 1}
                >{placeLabel(item.placement)}/{item.total_starters}</span
              >
            {:else if item.status === "finished"}
              <span class="dnf"
                >DNF{item.total_starters ? `/${item.total_starters}` : ""}</span
              >
            {:else if item.status === "running"}
              <span
                >{item.type === "daily_participant" ? "Active" : "Racing"}</span
              >
              {#if item.total_starters}
                <span
                  >{item.total_starters} player{item.total_starters !== 1
                    ? "s"
                    : ""}</span
                >
              {/if}
            {:else if item.type === "race_participant"}
              <span>Joined</span>
            {/if}
            {#if item.igt_ms > 0}
              <span>{formatIgt(item.igt_ms)}</span>
              <span>&dagger; {item.death_count}</span>
            {/if}
          {:else if item.type === "race_organizer"}
            <span>Organized</span>
            <span
              >{item.participant_count} player{item.participant_count !== 1
                ? "s"
                : ""}</span
            >
          {:else if item.type === "race_caster"}
            <span>Casted</span>
          {:else if item.type === "training"}
            {#if item.status === "active"}
              <span>Active</span>
            {:else if item.status === "abandoned"}
              <span class="dnf">DNF</span>
            {/if}
            {#if item.igt_ms > 0}
              <span>{formatIgt(item.igt_ms)}</span>
              <span>&dagger; {item.death_count}</span>
            {/if}
          {/if}
        </span>
      </span>
      <span class="act-date">{formatDate(item.date)}</span>
    </a>
  {/each}
</div>

<style>
  .act-list {
    border-top: 1px solid var(--color-border);
  }

  .act-row {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr) auto;
    align-items: center;
    gap: 1.25rem;
    padding: 0.6rem 0.25rem;
    border-bottom: 1px solid var(--color-border);
    text-decoration: none;
    color: inherit;
    transition: background var(--transition);
  }

  .act-row:hover {
    background: var(--color-surface-elevated);
  }

  .act-kind {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .mark {
    flex: none;
    display: inline-block;
  }

  .mark-race {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    border: 2px solid var(--color-gold);
  }

  .mark-daily {
    width: 8px;
    height: 8px;
    background: var(--color-success);
    transform: rotate(45deg);
  }

  .mark-solo {
    width: 8px;
    height: 8px;
    border: 2px solid var(--color-info);
  }

  .act-main {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .t {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    min-width: 0;
  }

  .t .title {
    font-weight: 500;
    font-size: var(--font-size-base);
    color: var(--color-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .m {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    margin-top: 1px;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--color-text-secondary);
  }

  .m > :global(span:not(:first-child))::before {
    content: "·";
    margin: 0 0.4rem;
    color: var(--color-text-disabled);
  }

  .m .dnf {
    color: var(--color-danger);
  }

  .m .place.first {
    color: var(--color-gold);
  }

  .act-date {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--color-text-secondary);
    white-space: nowrap;
  }

  @media (max-width: 640px) {
    .act-row {
      grid-template-columns: 68px minmax(0, 1fr) auto;
      gap: 0.75rem;
    }
  }
</style>
