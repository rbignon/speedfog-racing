<script lang="ts">
  import { onMount } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { fetchEvent, getTwitchLoginUrl, type EventDetail } from "$lib/api";
  import {
    blockOrder,
    champions,
    eventFacts,
    formatEventDate,
    formatEventDay,
    liveStage,
    pollIntervalMs,
    fillSlots,
    ordinal,
    racesSection,
    shownStage,
    stageTimes,
    stripStagePrefix,
  } from "$lib/events";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import UserLink from "$lib/components/UserLink.svelte";
  import RaceCard from "$lib/components/RaceCard.svelte";
  import EventTimeline from "$lib/components/events/EventTimeline.svelte";
  import EventSeedCard from "$lib/components/events/EventSeedCard.svelte";
  import EventLadder from "$lib/components/events/EventLadder.svelte";
  import EventQualified from "$lib/components/events/EventQualified.svelte";
  import EventLiveStrip from "$lib/components/events/EventLiveStrip.svelte";
  import EventBracket from "$lib/components/events/EventBracket.svelte";
  import EventRacePlaceholder from "$lib/components/events/EventRacePlaceholder.svelte";
  import EventIntro from "$lib/components/events/EventIntro.svelte";
  import EventPractice from "$lib/components/events/EventPractice.svelte";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  // Writable $derived: starts from the route's loaded data and stays synced
  // to it (so navigating from one event to another, or an invalidateAll(),
  // replaces it), while still letting refresh()'s poll below reassign it
  // in between navigations.
  let detail: EventDetail = $derived(data.detail);

  let now = $state(new Date());

  const fmt = (iso: string) => formatEventDate(iso);
  // Carries the timezone, for the instants still ahead of the viewer. What
  // they can no longer act on keeps the plain form.
  const fmtZone = (iso: string) => formatEventDate(iso, true);
  const fmtDay = (iso: string) => formatEventDay(iso);

  let blocks = $derived(blockOrder(detail.phase));
  let facts = $derived(eventFacts(detail, fmtDay));
  let seedsByMode = $derived(
    detail.modes.map((mode) => ({
      mode,
      slots: fillSlots(
        detail.qualifier_races.filter((r) => r.mode === mode.key),
        detail.seeds_per_mode,
      ),
    })),
  );
  let seedsOpenAt = $derived(
    detail.phase === "upcoming" ? detail.starts_at : null,
  );
  let semis = $derived(detail.stages.filter((s) => s.kind === "semi"));
  let semiPlaces = $derived(semis.reduce((n, s) => n + s.field.length, 0));
  let newcomersStage = $derived(
    detail.stages.find((s) => s.kind === "newcomers"),
  );
  let finalStage = $derived(detail.stages.find((s) => s.kind === "final"));
  let eveningTimes = $derived(stageTimes(detail.stages));
  let shown = $derived(shownStage(detail));
  let crowned = $derived(champions(detail));
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
  <title>{detail.name} - SpeedFog Racing</title>
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
    {#if block === "intro"}
      <section>
        <SectionTitle>What is SpeedFog?</SectionTitle>
        <EventIntro />
      </section>
    {:else if block === "format"}
      <section>
        <SectionTitle>The format</SectionTitle>
        <div class="fmt">
          <div class="prose">
            <p>
              <strong
                >{detail.seeds_per_mode * detail.modes.length} seeds, {detail
                  .modes.length} modes, one window.</strong
              >
              From <span class="date">{fmtDay(detail.starts_at)}</span> to
              <span class="date">{fmtDay(detail.qualifier_ends_at)}</span>, {detail.seeds_per_mode}
              seeds are open in each of
              {detail.modes.map((m) => m.label).join(", ")}. Play at least one
              seed per mode, whenever you want; the better of your seeds counts.
              Each seed scores like a daily: rank points, 100 to first, down the
              field.
            </p>
            <p>
              <strong
                >The top {semiPlaces} on the ladder go to the playoffs</strong
              >:
              {#each semis as stage, i (stage.key)}{i > 0
                  ? ", "
                  : ""}{stage.label}
                on
                <span class="date">{fmtDay(stage.date)}</span
                >{/each}{#if finalStage}, then the {finalStage.label} on
                <span class="date">{fmtDay(finalStage.date)}</span>{/if}.
              {#if eveningTimes}Playoff evenings start at {eveningTimes.time} in your
                timezone{#if eveningTimes.exception}, the {eveningTimes
                    .exception.label} at {eveningTimes.exception
                    .time}{/if}.{/if}
            </p>
            {#if newcomersStage}
              <p>
                <strong>Newcomers get a final of their own</strong>
                on <span class="date">{fmtDay(newcomersStage.date)}</span>. You
                are a newcomer if you had finished fewer than {detail.newcomer_threshold}
                SpeedFog races or daily seeds when the qualifier opened on
                <span class="date">{fmtDay(detail.starts_at)}</span>; the {newcomersStage
                  .field.length} best newcomers outside the top {semiPlaces} make
                up its field.
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
                <h3>Sign in</h3>
                {#if auth.user}
                  <p class="signed-in">
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="3"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      aria-hidden="true"
                      ><polyline points="20 6 9 17 4 12" /></svg
                    >
                    Signed in as
                    <UserLink user={auth.user} showAvatar />
                  </p>
                {:else}
                  <a
                    href={getTwitchLoginUrl()}
                    class="btn btn-twitch"
                    data-sveltekit-reload
                    onclick={() =>
                      sessionStorage.setItem(
                        "redirect_after_login",
                        window.location.pathname,
                      )}>Sign in with Twitch</a
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
                    ? `Seeds open ${fmtZone(detail.starts_at)}.`
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
                  At least one seed of each mode before {fmtZone(
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
    {:else if block === "practice"}
      <section>
        <SectionTitle>Practice first</SectionTitle>
        <p class="note">
          A solo seed never counts toward the ladder, and neither does the
          <a href="/daily">Daily Seed</a>: one shared seed a day.
        </p>
        <EventPractice modes={detail.modes} />
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
    {:else if block === "ladder_qualified"}
      <section class="two-col">
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
            formatDate={fmtZone}
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
      {/if}
    {:else if block === "champions"}
      {#if crowned.length > 0}
        <section class="podium" aria-label="Winners">
          {#each crowned as champion (champion.kind)}
            {@const first = champion.kind === "final"}
            <div class="plate" class:first>
              <span class="chip plate-chip">{champion.label}</span>
              {#if champion.user.twitch_avatar_url}
                <img
                  class="plate-avatar"
                  src={champion.user.twitch_avatar_url}
                  alt=""
                />
              {:else}
                <span
                  class="plate-avatar plate-avatar-placeholder"
                  aria-hidden="true"
                  >{(
                    champion.user.twitch_display_name ||
                    champion.user.twitch_username
                  )
                    .charAt(0)
                    .toUpperCase()}</span
                >
              {/if}
              <div class="plate-name">
                <UserLink user={champion.user} showBadge />
              </div>
              <div class="plate-stats">
                {#if champion.ladderRank !== null}
                  <div>
                    <span class="n">{ordinal(champion.ladderRank)}</span><span
                      class="k">qualified</span
                    >
                  </div>
                {/if}
                <div>
                  <span class="n"
                    >{champion.wins} of {champion.racesExpected}</span
                  ><span class="k">wins</span>
                </div>
                {#if champion.weapon}
                  <div class="wide">
                    <span class="n text">{champion.weapon}</span><span class="k"
                      >signature weapon</span
                    >
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        </section>
      {/if}
    {:else if block === "bracket_ladder"}
      <section class="bracket-block">
        <div class="two-col wide-left">
          <div>
            <SectionTitle>Bracket</SectionTitle>
            <EventBracket stages={detail.stages} formatDay={fmtDay} />
          </div>
          <div class="stack">
            {#if shown}
              {@const section = racesSection(detail, fmtZone, now)}
              <div>
                <SectionTitle>{shown.label}</SectionTitle>
                {#if section}
                  <p class="meta-row">
                    <span class="signal {section.signal.cls}"
                      >{section.signal.text}</span
                    >
                    <span class="meta-right">{section.meta}</span>
                  </p>
                {/if}
                <div class="stage-races">
                  {#each fillSlots(shown.races, shown.races_expected) as entry, i (i)}
                    {#if entry}
                      <RaceCard
                        race={entry.race}
                        title={stripStagePrefix(entry.race.name, shown.label)}
                        showFoot={false}
                        showRole={false}
                      />
                    {:else}
                      <EventRacePlaceholder
                        name={[`Race ${i + 1}`, shown.modes[i]]
                          .filter(Boolean)
                          .join(" - ")}
                        users={shown.field
                          .map((slot) => slot.user)
                          .filter((user) => user !== null)}
                      />
                    {/if}
                  {/each}
                </div>
              </div>
            {/if}
            {#if detail.playoff_rules.length > 0}
              <div class="rules-card">
                <h3>Playoff rules</h3>
                <ul>
                  {#each detail.playoff_rules as rule, i (i)}<li>
                      {rule}
                    </li>{/each}
                </ul>
              </div>
            {/if}
          </div>
        </div>
        <div class="ladder-col">
          <SectionTitle>Qualifier ladder</SectionTitle>
          <p class="meta-row">
            <span
              class="signal {detail.ladder.provisional
                ? 'signal-active'
                : 'signal-finished'}"
              >{detail.ladder.provisional ? "Provisional" : "Final"}</span
            >
            <span class="fact-row">
              <span class="fact"
                ><span class="k">Closed</span><span class="v"
                  >{fmt(detail.qualifier_ends_at)}</span
                ></span
              >
              <span class="fact"
                ><span class="k">Entered</span><span class="v"
                  >{detail.ladder.entered}</span
                ></span
              >
              <span class="fact"
                ><span class="k">Ranked</span><span class="v"
                  >{detail.ladder.ranked_count}</span
                ></span
              >
            </span>
          </p>
          <div class="panel">
            <EventLadder
              ladder={detail.ladder}
              modes={detail.modes}
              viewerId={auth.user?.id ?? null}
            />
          </div>
        </div>
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
  /* Dates carry the brass the timeline and the step numbers already use, so
   * they surface out of the paragraph without a second bold. */
  .prose .date {
    color: var(--color-gold);
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
  /* The step stands done: the confirmation carries the verdigris, the name
   * beside it stays a name (its own reward colours included). */
  .step .signed-in {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--color-success);
    /* Narrow enough and the flex row would squeeze the label itself: the
     * name is the part that gives, ellipsised by UserLink. */
    white-space: nowrap;
  }
  .step .signed-in svg {
    flex: none;
  }
  .step .signed-in :global(.user-link) {
    color: var(--color-text);
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
  .ladder-col {
    min-width: 0;
  }
  .meta-row {
    margin: 0 0 14px;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.5rem;
  }
  .meta-row .fact-row {
    margin-left: auto;
  }
  .meta-right {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }
  /* The decided winners: two compact plates centred under the band, the
   * champion's larger and on the fog accent, with the evening's figures. */
  .podium {
    display: flex;
    justify-content: center;
    align-items: center;
    flex-wrap: wrap;
    gap: 24px;
    padding: 0.4rem 0;
  }
  .plate {
    width: min(232px, 100%);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1.1rem 1rem 1rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.7rem;
    text-align: center;
  }
  .plate.first {
    width: min(280px, 100%);
    padding: 1.4rem 1.2rem 1.2rem;
    border-color: var(--color-purple);
    box-shadow: var(--glow-fog);
  }
  .plate.first .plate-chip {
    color: var(--color-purple-hover);
    border-color: var(--color-purple);
  }
  .plate-avatar {
    width: 84px;
    height: 84px;
    border-radius: 50%;
    border: 2px solid var(--color-border);
    object-fit: cover;
  }
  .plate.first .plate-avatar {
    width: 120px;
    height: 120px;
    border: 3px solid var(--color-purple);
    box-shadow: var(--glow-fog);
  }
  .plate-avatar-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-family: var(--font-display);
    font-size: 2rem;
    font-weight: 600;
  }
  .plate-name {
    font-size: var(--font-size-lg);
    font-weight: 600;
  }
  .plate.first .plate-name {
    font-size: 1.4rem;
  }
  .plate-stats {
    display: flex;
    flex-wrap: wrap;
    row-gap: 0.7rem;
    width: 100%;
    margin-top: 0.2rem;
    padding-top: 0.7rem;
    border-top: 1px solid var(--color-border);
  }
  .plate-stats > div {
    flex: 1 1 40%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }
  .plate-stats > .wide {
    flex-basis: 100%;
  }
  .plate-stats .n {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
  }
  .plate-stats .n.text {
    font-size: 1rem;
    line-height: 1.2;
  }
  .plate.first .plate-stats .n {
    color: var(--color-purple-hover);
  }
  .plate-stats .k {
    font-family: var(--font-mono);
    font-size: 0.62rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }
  .bracket-block {
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }
  .panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.1rem;
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
  /* Too narrow to hold both ends apart: the right-hand side joins the signal
   * on the left, wrapping under it when it does not fit. */
  @media (max-width: 640px) {
    .meta-row .fact-row,
    .meta-row .meta-right {
      margin-left: 0;
    }
  }
  @media (max-width: 900px) {
    .fmt,
    .take-part,
    .cards,
    .two-col,
    .two-col.wide-left {
      grid-template-columns: 1fr;
    }
  }
</style>
