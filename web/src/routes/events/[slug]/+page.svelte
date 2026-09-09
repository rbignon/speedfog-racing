<script lang="ts">
  import { onMount } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { fetchEvent, getTwitchLoginUrl, type EventDetail } from "$lib/api";
  import {
    blockOrder,
    eventFacts,
    formatEventDate,
    formatEventDay,
    liveStage,
    pollIntervalMs,
    racesSectionTitle,
    seedSlots,
  } from "$lib/events";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import RaceCard from "$lib/components/RaceCard.svelte";
  import EventTimeline from "$lib/components/events/EventTimeline.svelte";
  import EventSeedCard from "$lib/components/events/EventSeedCard.svelte";
  import EventLadder from "$lib/components/events/EventLadder.svelte";
  import EventQualified from "$lib/components/events/EventQualified.svelte";
  import EventLiveStrip from "$lib/components/events/EventLiveStrip.svelte";
  import EventBracket from "$lib/components/events/EventBracket.svelte";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  // Writable $derived: starts from the route's loaded data and stays synced
  // to it (so navigating from one event to another, or an invalidateAll(),
  // replaces it), while still letting refresh()'s poll below reassign it
  // in between navigations.
  let detail: EventDetail = $derived(data.detail);

  let now = $state(new Date());

  const fmt = (iso: string) => formatEventDate(iso);
  const fmtDay = (iso: string) => formatEventDay(iso);

  let blocks = $derived(blockOrder(detail.phase));
  let facts = $derived(eventFacts(detail, fmtDay));
  let seedsByMode = $derived(
    detail.modes.map((mode) => ({
      mode,
      slots: seedSlots(
        detail.qualifier_races.filter((r) => r.mode === mode.key),
        detail.seeds_per_mode,
      ),
    })),
  );
  let seedsOpenAt = $derived(
    detail.phase === "upcoming" ? detail.starts_at : null,
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
    let pollMs: number | null = null;
    const arm = () => {
      const ms = pollIntervalMs(detail, new Date());
      if (ms === pollMs) return;
      if (poll !== null) clearInterval(poll);
      poll = ms === null ? null : setInterval(refresh, ms);
      pollMs = ms;
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
    <div class="band-left">
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
            </p>
            {#if newcomersStage}
              <p>
                <strong>The best newcomers</strong> (fewer than {detail.newcomer_threshold}
                finished SpeedFog races before {fmt(detail.starts_at)}) get
                their own final on {fmt(newcomersStage.date)}.
              </p>
            {/if}
          </div>
          <div class="facts">
            {#each facts as fact, i (i)}
              <div>
                <span class="k">{fact.title}</span>
                <span class="v"
                  >{#each fact.lines as line, i (i)}<span>{line}</span
                    >{/each}</span
                >
              </div>
            {/each}
          </div>
        </div>
      </section>
    {:else if block === "take_part"}
      <section>
        <SectionTitle>Take part</SectionTitle>
        <div class="take-part">
          <div class="steps">
            <div class="step">
              <span class="n">01</span>
              <div class="step-body">
                <h3>Sign in with Twitch</h3>
                <p>
                  Spectating needs no account. Playing does: one click, nothing
                  else to fill in.
                </p>
                {#if !auth.isLoggedIn}
                  <a
                    href={getTwitchLoginUrl()}
                    class="btn btn-twitch"
                    data-sveltekit-reload>Sign in with Twitch</a
                  >
                {/if}
              </div>
            </div>
            <div class="step">
              <span class="n">02</span>
              <div class="step-body">
                <h3>Pick a seed, download the pack</h3>
                <p>
                  {detail.phase === "upcoming"
                    ? `Seeds open ${fmt(detail.starts_at)}.`
                    : "Any of the seeds below."} The pack holds everything, game files
                  and overlay. Nothing to install by hand.
                </p>
              </div>
            </div>
            <div class="step">
              <span class="n">03</span>
              <div class="step-body">
                <h3>Run it in one sitting</h3>
                <p>
                  At least one seed of each mode before {fmt(
                    detail.qualifier_ends_at,
                  )}. Thirty minutes without progress ends a run.
                </p>
              </div>
            </div>
          </div>
          <div class="side-cards">
            <div id="rules" class="rules-card">
              <h3>Rules</h3>
              <ul>
                {#each detail.rules as rule, i (i)}<li>{rule}</li>{/each}
              </ul>
            </div>
            <div class="rules-card tips-card">
              <h3>Tips</h3>
              <ul>
                <li>
                  Warm up on the <a href="/daily">Daily Seed</a>: one shared
                  seed a day, scored like a qualifier seed.
                </li>
                <li>
                  Run a <a href="/training">solo seed</a> of each mode before your
                  qualifier seeds; solos never count toward the ladder.
                </li>
                <li>
                  Skips and route knowledge are on the
                  <a href="/zones">Zones</a> page.
                </li>
                <li>
                  Read the <a href="/game-changes">Game changes</a> once: bosses,
                  items and the route differ from vanilla.
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>
    {:else if block === "seeds"}
      <section>
        <SectionTitle>Qualifier seeds</SectionTitle>
        <p class="note">The better of your seeds counts.</p>
        {#each seedsByMode as group (group.mode.key)}
          <div class="mode-group">
            <h3>{group.mode.label}</h3>
            <div class="cards">
              {#each group.slots as entry, i (i)}
                <EventSeedCard
                  {entry}
                  index={i + 1}
                  modeLabel={group.mode.label}
                  partner={detail.partner_name}
                  {now}
                  opensAt={seedsOpenAt}
                />
              {/each}
            </div>
          </div>
        {/each}
      </section>
    {:else if block === "ladder_qualified" || block === "qualified_ladder"}
      <section class="two-col" class:reversed={block === "qualified_ladder"}>
        <div class="ladder-col">
          <SectionTitle>Ladder</SectionTitle>
          <p class="meta-row">
            <span
              class="signal {detail.ladder.provisional
                ? 'signal-active'
                : 'signal-finished'}"
              >{detail.ladder.provisional ? "Provisional" : "Final"}</span
            >
          </p>
          <div class="panel">
            <EventLadder
              ladder={detail.ladder}
              modes={detail.modes}
              viewerId={auth.user?.id ?? null}
            />
          </div>
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
    {:else if block === "live"}
      {#if detail.live_race}
        {@const stage = liveStage(detail)}
        {@const index =
          stage?.races.find((r) => r.race.id === detail.live_race?.id)?.index ??
          null}
        <EventLiveStrip race={detail.live_race} {stage} raceIndex={index} />
      {:else if detail.next_stage}
        <div class="upnext">
          <span class="signal signal-setup">Up next</span>
          <span class="upnext-title"
            >{detail.next_stage.label} &middot; {fmt(
              detail.next_stage.date,
            )}</span
          >
        </div>
      {/if}
    {:else if block === "bracket_ladder"}
      <section class="two-col wide-left">
        <div class="stack">
          <div>
            <SectionTitle>Bracket</SectionTitle>
            <EventBracket
              stages={detail.stages}
              formatDate={fmt}
              formatDay={fmtDay}
            />
          </div>
          <div class="panel">
            <div class="panel-head">
              <SectionTitle>Qualifier ladder</SectionTitle>
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
              note={`Closed ${fmt(detail.qualifier_ends_at)} · ${detail.ladder.entered} entered, ${detail.ladder.ranked_count} ranked`}
            />
          </div>
        </div>
        <div class="stack">
          {#if detail.phase === "playoffs"}
            {@const current =
              detail.stages.find((s) => s.key === detail.current_stage_key) ??
              null}
            <div>
              <SectionTitle>{racesSectionTitle(detail, fmt)}</SectionTitle>
              {#if current && current.races.length > 0}
                <div class="stage-races">
                  {#each current.races as entry (entry.slot)}<RaceCard
                      race={entry.race}
                    />{/each}
                </div>
              {:else}
                <p class="note">Races are announced on the day.</p>
              {/if}
            </div>
          {/if}
          <div id="rules" class="rules-card">
            <h3>Rules</h3>
            <ul>
              {#each detail.rules as rule, i (i)}<li>{rule}</li>{/each}
            </ul>
          </div>
        </div>
      </section>
    {:else if block === "rules"}
      <section id="rules" class="rules-card">
        <h3>Rules</h3>
        <ul>
          {#each detail.rules as rule, i (i)}<li>{rule}</li>{/each}
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
  .band-left {
    flex: 1 1 640px;
    min-width: 0;
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
    display: flex;
    flex-direction: column;
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    line-height: 1.25;
    text-transform: uppercase;
    margin-top: 1px;
  }
  .take-part {
    display: grid;
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
    gap: 24px;
    align-items: start;
  }
  .steps {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .step {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.1rem;
    display: grid;
    grid-template-columns: 2.4rem minmax(0, 1fr);
    align-items: start;
  }
  .step-body {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .step .n {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.09em;
    color: var(--color-gold);
    padding-top: 0.35rem;
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
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 0.06em;
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
  .two-col.reversed > .ladder-col {
    order: 2;
  }
  .ladder-col {
    min-width: 0;
  }
  .meta-row {
    margin: 0 0 14px;
    display: flex;
    align-items: center;
    gap: 0.5rem;
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
  .side-cards {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .rules-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-sm);
    padding: 0.75rem 1rem;
  }
  .tips-card {
    border-left-color: var(--color-info);
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
  .upnext {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.9rem 1.1rem;
  }
  .upnext-title {
    font-family: var(--font-display);
    font-size: 1.3rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }
  .two-col.wide-left {
    grid-template-columns: minmax(0, 8fr) minmax(0, 4fr);
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2rem;
    min-width: 0;
  }
  .stage-races {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  @media (max-width: 900px) {
    .fmt,
    .take-part,
    .cards,
    .two-col,
    .two-col.reversed,
    .two-col.wide-left {
      grid-template-columns: 1fr;
    }
    .two-col.reversed > .ladder-col {
      order: 0;
    }
  }
</style>
