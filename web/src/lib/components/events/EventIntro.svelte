<script lang="ts">
  import { auth } from "$lib/stores/auth.svelte";
  import { getTwitchLoginUrl } from "$lib/api";
  import EventTrailer from "./EventTrailer.svelte";

  // The trailer beside the text, its loop cut before the date card.
  const LOOP_SRC = "/events/season-one-trailer.mp4";
  const TRAILER_URL = "https://youtu.be/V8ONFNyNgdA";
  const STILL_SRC = "/events/season-one-trailer-poster.webp";
</script>

<div class="intro">
  <p class="lead">
    <strong>Elden Ring as a race, in about an hour.</strong>
    SpeedFog builds on thefifthmatt's
    <a
      href="https://www.nexusmods.com/eldenring/mods/3295"
      target="_blank"
      rel="noopener noreferrer">Fog Gate Randomizer</a
    >: every fog gate leads to a random zone, chained into a route that ends on
    a final boss drawn from the game's majors.
  </p>
  <div class="text">
    <dl class="concepts">
      <div>
        <dt>Pick your fog</dt>
        <dd>
          The route <strong>splits and merges</strong>: at each fork you choose
          a gate without knowing what lies behind it.<br />Parallel branches are
          <strong>equally deep and equally hard</strong>, with the same number
          of bosses.
        </dd>
      </div>
      <div>
        <dt>Care package</dt>
        <dd>
          Every seed starts you with golden seeds, sacred tears, your
          <strong>Great Runes restored</strong>, and a care package of random
          spells, catalysts, talismans and armor, with your class weapon at
          <strong>maximum upgrade</strong>. Stat requirements are gone, so all
          of it is usable straight away.
        </dd>
      </div>
      <div>
        <dt>Dying doesn't matter, time does</dt>
        <dd>
          Enemies <strong>get tougher the deeper you go</strong>, but a death
          costs <strong>nothing but the time it takes to get back</strong>, so a
          risk is usually worth taking.
        </dd>
      </div>
    </dl>
    <!-- Signed out only: a reader who already has an account knows both what
         SpeedFog is and where to play it. The primary is the home page's own
         call, and goes through Twitch the same way: storing no redirect
         leaves the callback on its default, the dashboard, where a new
         account is walked through its first run. -->
    {#if !auth.user}
      <div class="cta">
        <a
          href={getTwitchLoginUrl()}
          class="btn btn-primary"
          data-sveltekit-reload>Try a seed</a
        >
        <a href="/about" class="btn btn-secondary">How it works</a>
      </div>
    {/if}
  </div>
  <EventTrailer src={LOOP_SRC} poster={STILL_SRC} url={TRAILER_URL} />
</div>

<style>
  .intro {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 24px;
    align-items: start;
  }
  .text {
    max-width: 70ch;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }
  .lead {
    grid-column: 1 / -1;
    margin: 0;
    color: var(--color-text-secondary);
  }
  .lead strong {
    color: var(--color-text);
  }
  .concepts {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
  }
  .concepts div {
    padding-left: 0.9rem;
    border-left: 2px solid var(--color-border);
  }
  .concepts dt {
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .concepts dd {
    margin: 0.15rem 0 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
  .concepts dd strong {
    color: var(--color-text);
  }
  .cta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  @media (max-width: 900px) {
    .intro {
      grid-template-columns: 1fr;
    }
  }
</style>
