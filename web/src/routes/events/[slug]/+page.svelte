<script lang="ts">
  import { onMount } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { fetchEvent, getTwitchLoginUrl, type EventDetail } from "$lib/api";
  import { blockOrder, formatEventDate, shouldPoll } from "$lib/events";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import EventTimeline from "$lib/components/events/EventTimeline.svelte";
  import EventSeedCard from "$lib/components/events/EventSeedCard.svelte";
  import EventLadder from "$lib/components/events/EventLadder.svelte";
  import EventQualified from "$lib/components/events/EventQualified.svelte";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();
  let detail: EventDetail = $state(data.detail);
  let now = $state(new Date());

  const fmt = (iso: string) => formatEventDate(iso);

  let blocks = $derived(blockOrder(detail.phase));
  let seedsByMode = $derived(
    detail.modes.map((mode) => ({
      mode,
      seeds: detail.qualifier_races.filter((r) => r.mode === mode.key),
    })),
  );
  let semis = $derived(detail.stages.filter((s) => s.kind === "semi"));
  let newcomersStage = $derived(
    detail.stages.find((s) => s.kind === "newcomers"),
  );
  let finalStage = $derived(detail.stages.find((s) => s.kind === "final"));
  let phaseSignal = $derived.by(() => {
    switch (detail.phase) {
      case "upcoming":
        return { cls: "signal-setup", text: `Opens ${fmt(detail.starts_at)}` };
      case "qualifier":
        return { cls: "signal-running", text: "Qualifier open" };
      case "cut":
        return { cls: "signal-active", text: "Qualifier closed" };
      case "playoffs":
        return { cls: "signal-running", text: "Playoffs" };
      case "finished":
        return { cls: "signal-finished", text: "Finished" };
    }
  });

  async function refresh() {
    try {
      detail = await fetchEvent(detail.slug);
    } catch {
      /* keep the last good state; the next tick retries */
    }
    now = new Date();
  }

  onMount(() => {
    const clock = setInterval(() => (now = new Date()), 60_000);
    let poll: ReturnType<typeof setInterval> | null = null;
    const arm = () => {
      if (shouldPoll(detail) && poll === null)
        poll = setInterval(refresh, 60_000);
      if (!shouldPoll(detail) && poll !== null) {
        clearInterval(poll);
        poll = null;
      }
    };
    arm();
    const watcher = setInterval(arm, 60_000);
    return () => {
      clearInterval(clock);
      clearInterval(watcher);
      if (poll) clearInterval(poll);
    };
  });
</script>

<svelte:head>
  <title>{detail.name} · SpeedFog Racing</title>
</svelte:head>

<div class="band">
  <div class="band-inner">
    <div>
      <span class="kicker"
        >SpeedFog{detail.partner_name ? ` × ${detail.partner_name}` : ""} &middot;
        {detail.name}</span
      >
      <h1>
        SpeedFog
        {#if detail.partner_name}<span class="cross">&times;</span>
          {detail.partner_name}{/if}
        <span class="brass">{detail.name}</span>
      </h1>
      <EventTimeline stops={detail.timeline} {now} />
    </div>
    <div class="band-right">
      {#if detail.partner_name}
        <div class="cobrand">
          <span class="partner-name">{detail.partner_name}</span>
          {#if detail.partner_logo_url}
            <img class="partner-logo" src={detail.partner_logo_url} alt="" />
          {:else}
            <span class="partner-logo placeholder"
              >{detail.partner_name.slice(0, 2).toUpperCase()}</span
            >
          {/if}
        </div>
      {/if}
      <span class="signal {phaseSignal.cls}">{phaseSignal.text}</span>
      <div class="band-actions">
        <a href="#rules" class="btn btn-outline">Rules</a>
        {#if detail.partner_url}
          <a
            href={detail.partner_url}
            class="btn btn-outline"
            target="_blank"
            rel="noopener noreferrer">{detail.partner_name} Discord</a
          >
        {/if}
      </div>
    </div>
  </div>
</div>

<main class="container">
  {#each blocks as block (block)}
    {#if block === "format"}
      <section>
        <SectionTitle>The format</SectionTitle>
        <div class="fmt">
          <div class="prose">
            <p>
              <strong
                >{detail.seeds_per_mode * detail.modes.length} seeds, {detail
                  .modes.length} modes, one window.</strong
              >
              From {fmt(detail.starts_at)} to {fmt(detail.qualifier_ends_at)}, {detail.seeds_per_mode}
              seeds are open in each of
              {detail.modes.map((m) => m.label).join(", ")}. Play at least one
              seed per mode, whenever you want; the better of your seeds counts.
              Each seed scores like a daily: rank points, 100 to first, down the
              field.
            </p>
            <p>
              <strong
                >The top {semis.reduce((n, s) => n + s.field.length, 0)} on the ladder
                go to the playoffs</strong
              >:
              {semis
                .map((s) => `${s.label} on ${fmt(s.date)}`)
                .join(", ")}{finalStage
                ? `, then the ${finalStage.label} on ${fmt(finalStage.date)}`
                : ""}.
              {#if newcomersStage}<strong>The best newcomers</strong> (fewer
                than {detail.newcomer_threshold}
                finished SpeedFog races before {fmt(detail.starts_at)}) get
                their own final on {fmt(newcomersStage.date)}.{/if}
            </p>
          </div>
          <div class="facts">
            <div>
              <span class="k">Qualifier</span><span class="v"
                >{detail.seeds_per_mode * detail.modes.length} seeds · {detail
                  .modes.length} modes</span
              >
            </div>
            <div>
              <span class="k">Modes</span><span class="v"
                >{detail.modes.map((m) => m.label).join(" · ")}</span
              >
            </div>
            <div>
              <span class="k">Playoffs</span><span class="v"
                >{detail.stages.filter((s) => s.kind !== "newcomers").length} Sundays
                · {detail.stages[0]?.races_expected ?? 3} races each</span
              >
            </div>
            {#if newcomersStage}
              <div>
                <span class="k">Newcomers</span><span class="v"
                  >Own final · {fmt(newcomersStage.date)}</span
                >
              </div>
            {/if}
          </div>
        </div>
      </section>
    {:else if block === "take_part"}
      <section>
        <SectionTitle>Take part</SectionTitle>
        <div class="steps">
          <div class="step">
            <span class="n">01</span>
            <h3>Sign in with Twitch</h3>
            <p>
              Spectating needs no account. Playing does: one click, nothing else
              to fill in.
            </p>
            {#if !auth.isLoggedIn}
              <a
                href={getTwitchLoginUrl()}
                class="btn btn-twitch"
                data-sveltekit-reload>Sign in with Twitch</a
              >
            {/if}
          </div>
          <div class="step">
            <span class="n">02</span>
            <h3>Pick a seed, download the pack</h3>
            <p>
              Any of the seeds below. The pack holds everything, game files and
              overlay. Nothing to install by hand.
            </p>
          </div>
          <div class="step">
            <span class="n">03</span>
            <h3>Run it in one sitting</h3>
            <p>
              At least one seed of each mode before {fmt(
                detail.qualifier_ends_at,
              )}. Thirty minutes without progress ends a run.
            </p>
          </div>
        </div>
      </section>
    {:else if block === "seeds"}
      <section>
        <SectionTitle>Qualifier seeds</SectionTitle>
        <p class="note">
          Open until {fmt(detail.qualifier_ends_at)} &middot; {detail.seeds_per_mode}
          seeds per mode &middot; the better of your seeds counts
        </p>
        {#each seedsByMode as group (group.mode.key)}
          <div class="mode-group">
            <h3>{group.mode.label}</h3>
            <div class="cards">
              {#each group.seeds as entry (entry.slot)}
                <EventSeedCard
                  {entry}
                  modeLabel={group.mode.label}
                  partner={detail.partner_name}
                  {now}
                />
              {/each}
              {#if group.seeds.length === 0}<p class="note">
                  Seeds appear here when the qualifier opens.
                </p>{/if}
            </div>
          </div>
        {/each}
      </section>
    {:else if block === "ladder_qualified" || block === "qualified_ladder"}
      <section class="two-col" class:reversed={block === "qualified_ladder"}>
        <div class="panel">
          <div class="panel-head">
            <SectionTitle>Ladder</SectionTitle>
            <span
              class="signal {detail.ladder.provisional
                ? 'signal-active'
                : 'signal-finished'}"
              >{detail.ladder.provisional ? "Provisional" : "Final"}</span
            >
          </div>
          <EventLadder
            ladder={detail.ladder}
            modes={detail.modes}
            viewerId={auth.user?.id ?? null}
            note={`Best seed per mode, ${detail.modes.length} modes summed · a score in every mode to be ranked · ${detail.ladder.entered} entered, ${detail.ladder.ranked_count} ranked`}
          />
        </div>
        <div>
          <SectionTitle>Qualified</SectionTitle>
          <EventQualified
            qualified={detail.qualified}
            stages={detail.stages}
            cutAt={detail.qualifier_ends_at}
            formatDate={fmt}
          />
        </div>
      </section>
    {:else if block === "rules"}
      <section id="rules" class="rules-card">
        <h3>Rules</h3>
        <ul>
          {#each detail.rules as rule (rule)}<li>{rule}</li>{/each}
        </ul>
      </section>
    {/if}
  {/each}
</main>

<style>
  .band {
    background: var(--color-surface);
    border-bottom: 1px solid var(--color-border);
  }
  .band-inner {
    max-width: 1180px;
    margin: 0 auto;
    padding: 1.6rem 2rem 1.4rem;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 2rem;
    flex-wrap: wrap;
  }
  .kicker {
    display: block;
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
    font-size: 0.7rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin-bottom: 0.25rem;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    line-height: 1.12;
  }
  h1 .cross {
    color: var(--color-text-secondary);
    font-weight: 500;
  }
  h1 .brass {
    color: var(--color-gold);
    font-weight: 600;
  }
  .band-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.5rem;
  }
  .cobrand {
    display: flex;
    align-items: center;
    gap: 0.9rem;
  }
  .partner-name {
    font-family: var(--font-display);
    font-weight: 700;
    font-size: 21px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .partner-logo {
    width: 44px;
    height: 44px;
    border-radius: var(--radius-sm);
    object-fit: contain;
  }
  .partner-logo.placeholder {
    border: 1px dashed var(--color-purple);
    color: var(--color-purple);
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-display);
    font-weight: 700;
    letter-spacing: 0.06em;
  }
  .band-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.2rem;
  }
  .container {
    max-width: 1180px;
    margin: 0 auto;
    padding: 1.5rem 2rem 3rem;
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }
  .note {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin: -0.6rem 0 0.9rem;
  }
  .prose {
    max-width: 70ch;
  }
  .prose p {
    color: var(--color-text-secondary);
    margin: 0 0 0.6rem;
  }
  .prose strong {
    color: var(--color-text);
  }
  .fmt {
    display: grid;
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
    gap: 24px;
    align-items: start;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1px;
    background: var(--color-border);
    border: 1px solid var(--color-border);
  }
  .facts div {
    background: var(--color-surface);
    padding: 0.6rem 0.8rem;
    display: flex;
    flex-direction: column;
  }
  .facts .k {
    font-family: var(--font-mono);
    font-size: 0.62rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }
  .facts .v {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    margin-top: 1px;
  }
  .steps {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 14px;
  }
  .step {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .step .n {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.09em;
    color: var(--color-gold);
  }
  .step h3 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
  }
  .step p {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
  .step .btn {
    align-self: flex-start;
  }
  .mode-group h3 {
    margin: 0 0 0.6rem;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }
  .mode-group + .mode-group {
    margin-top: 1.2rem;
  }
  .cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
  }
  .two-col {
    display: grid;
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
    gap: 24px;
    align-items: start;
  }
  .two-col.reversed {
    grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  }
  .two-col.reversed > .panel {
    order: 2;
  }
  .panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.1rem;
  }
  .panel-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
  }
  .rules-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-sm);
    padding: 0.75rem 1rem;
  }
  .rules-card h3 {
    margin: 0;
    font-size: var(--font-size-base);
  }
  .rules-card ul {
    margin: 0.5rem 0 0;
    padding-left: 1.25rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
  @media (max-width: 900px) {
    .fmt,
    .steps,
    .cards,
    .two-col,
    .two-col.reversed {
      grid-template-columns: 1fr;
    }
    .two-col.reversed > .panel {
      order: 0;
    }
  }
</style>
