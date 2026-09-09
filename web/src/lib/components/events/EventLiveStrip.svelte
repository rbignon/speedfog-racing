<script lang="ts">
  import type { EventStage, Race } from "$lib/api";
  import { formatPoolName } from "$lib/utils/format";

  let {
    race,
    stage,
    raceIndex,
  }: { race: Race; stage: EventStage | null; raceIndex: number | null } =
    $props();
  let runners = $derived(
    race.participant_previews
      .map((p) => p.twitch_display_name || p.twitch_username)
      .join(", "),
  );
  let liveCasters = $derived(race.casters.filter((c) => c.is_live));
  let watchUrl = $derived(
    liveCasters[0]?.stream_url ??
      (race.casters[0]
        ? `https://twitch.tv/${race.casters[0].user.twitch_username}`
        : null),
  );
  let startedAt = $derived(
    race.started_at
      ? new Intl.DateTimeFormat("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(new Date(race.started_at))
      : null,
  );
  // Built from arrays of non-empty parts (rather than inline {#if}
  // fragments) so the " · " separator only ever sits between two real
  // parts: no dangling leading dot, no missing space when Svelte collapses
  // the whitespace around an {#if} block.
  let titleParts = $derived(
    [
      stage?.label ?? "Playoff",
      raceIndex !== null && stage
        ? `Race ${raceIndex} of ${stage.races_expected}`
        : null,
      race.pool_name
        ? race.pool_display_name || formatPoolName(race.pool_name)
        : null,
    ].filter((part): part is string => Boolean(part)),
  );
  let subParts = $derived(
    [runners || null, startedAt ? `started ${startedAt}` : null].filter(
      (part): part is string => Boolean(part),
    ),
  );
</script>

<div class="strip">
  <div>
    <span class="signal signal-running">Live now</span>
    <div class="title">{titleParts.join(" · ")}</div>
    <div class="sub">{subParts.join(" · ")}</div>
    {#if race.casters.length > 0}
      <div class="casters">
        <svg
          viewBox="0 0 24 24"
          fill="currentColor"
          width="12"
          height="12"
          aria-hidden="true"
          ><path
            d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
          /></svg
        >
        <span>Cast by</span>
        {#each race.casters as caster, i (caster.id)}
          {#if i > 0}<span class="sep">&middot;</span>{/if}
          <a
            href="https://twitch.tv/{caster.user.twitch_username}"
            target="_blank"
            rel="noopener noreferrer"
            >{caster.user.twitch_display_name || caster.user.twitch_username}</a
          >
        {/each}
      </div>
    {/if}
  </div>
  <div class="actions">
    <a href="/race/{race.id}" class="btn btn-outline">Race page</a>
    {#if watchUrl}<a
        href={watchUrl}
        class="btn btn-twitch"
        target="_blank"
        rel="noopener noreferrer">Watch on Twitch</a
      >{/if}
  </div>
</div>

<style>
  .strip {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-danger);
    border-radius: var(--radius-sm);
    padding: 0.9rem 1.1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    flex-wrap: wrap;
  }
  .title {
    font-family: var(--font-display);
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  .sub {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-top: 2px;
  }
  .casters {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: var(--font-size-xs);
    color: var(--color-twitch-hover);
    margin-top: 0.4rem;
  }
  .casters a {
    color: inherit;
  }
  .sep {
    color: var(--color-text-disabled);
  }
  .actions {
    display: flex;
    gap: 0.6rem;
    align-items: center;
  }
</style>
