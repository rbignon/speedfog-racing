<script lang="ts">
  import { PUBLIC_BASE_URL } from "$env/static/public";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import MetroDag from "$lib/dag/MetroDag.svelte";
  import heroSeed from "$lib/data/hero-seed.json";
</script>

<svelte:head>
  <title>About – SpeedFog Racing</title>
  <meta
    name="description"
    content="Learn how SpeedFog Racing works: race through randomized Elden Ring fog gates with a daily seed challenge, live leaderboards, and metro-style progression maps."
  />
  <link rel="canonical" href="{PUBLIC_BASE_URL}/about" />
</svelte:head>

<main class="about">
  <header class="about-hero">
    <h1>How SpeedFog Racing Works</h1>
    <p>Race through a randomized Elden Ring.</p>
  </header>

  <section class="section">
    <SectionTitle>What is SpeedFog?</SectionTitle>
    <p>
      The <a
        href="https://www.nexusmods.com/eldenring/mods/3295"
        target="_blank"
        rel="noopener noreferrer">Fog Gate Randomizer</a
      >
      by <strong>thefifthmatt</strong> is an Elden Ring mod that replaces every fog
      gate with a randomized connection. Instead of walking through a familiar door
      into the expected area, each gate teleports you somewhere entirely different.
    </p>
    <p>
      Speedfog is a competitive racing platform, letting players race through
      <strong>balanced</strong> route maps where every path is equally long and
      challenging. Compete in organized multiplayer races, take on a new
      <strong>daily seed</strong>, or practice solo at your own pace. It
      features live leaderboards, an in-game overlay with progress tracking, and
      an interactive <strong>metro-style graph</strong> showing each player's path
      through the fog.
    </p>
  </section>

  <section class="section">
    <SectionTitle>Key Features</SectionTitle>
    <div class="feature-grid">
      <div class="feature-card">
        <strong>Balanced Paths</strong>
        <p>
          Every path through the map has the same structure and difficulty. No
          shortcut, no lucky route, only execution matters.
        </p>
      </div>
      <div class="feature-card">
        <strong>Daily Seed</strong>
        <p>
          A new seed every day, the same for everyone. Race the clock
          asynchronously, climb the daily and weekly leaderboards, and keep your
          streak alive.
        </p>
      </div>
      <div class="feature-card">
        <strong>Zone Tracking</strong>
        <p>
          Every fog gate traversal is detected automatically, feeding real-time
          zone progression and time gaps into the live leaderboard.
        </p>
      </div>
      <div class="feature-card">
        <strong>Solo Mode</strong>
        <p>
          Play on fresh seeds at your own pace, no account required. Your
          sessions are saved with times, deaths, and route maps.
        </p>
      </div>
      <div class="feature-card">
        <strong>Care Package</strong>
        <p>
          Every run starts with a randomized build: weapons, armor, spells, and
          talismans. Same seed, same build, fair from the first fog gate.
        </p>
      </div>
      <div class="feature-card">
        <strong>Multiple Formats</strong>
        <p>
          Sprint, Standard, or Hardcore: select a game mode that fits your
          playstyle. From quick 30-minute runs to punishing gauntlets.
        </p>
      </div>
    </div>
  </section>

  <section class="section">
    <SectionTitle>How Races Work</SectionTitle>
    <div class="steps">
      <div class="step">
        <span class="step-number">1</span>
        <div>
          <strong>Set up</strong>
          <p>
            An organizer creates a race and adds the participants who will
            compete, then shares an invite link.
          </p>
        </div>
      </div>
      <div class="step">
        <span class="step-number">2</span>
        <div>
          <strong>Download and launch</strong>
          <p>
            Each participant downloads a seed pack. Just run the executable, no
            setup required. Everyone gets the same randomized world.
          </p>
        </div>
      </div>
      <div class="step">
        <span class="step-number">3</span>
        <div>
          <strong>Race</strong>
          <p>
            Everyone starts at the same time. An in-game overlay tracks your
            progress and shows a live leaderboard, no need to alt-tab.
          </p>
        </div>
      </div>
      <div class="step">
        <span class="step-number">4</span>
        <div>
          <strong>Victory</strong>
          <p>
            The first player to defeat the final boss wins. The full route map
            is revealed to everyone once the race ends.
          </p>
        </div>
      </div>
    </div>
  </section>

  <section class="section">
    <SectionTitle>The Route Map</SectionTitle>
    <p>
      Every seed generates a unique route map, a network of fog gates connecting
      zones across the Lands Between. SpeedFog Racing displays it as a
      <strong>metro-style map</strong> so spectators and casters can follow each player's
      progression in real time.
    </p>
    <p>
      The map is structured by <strong>increasing depth</strong>: mini dungeons,
      legacy dungeons, boss arenas, and major bosses. Every parallel path is
      balanced: same length, same challenge. The final destination is always a
      random major boss.
    </p>
    <div class="dag-demo">
      <MetroDag graphJson={heroSeed} />
    </div>
    <p class="dag-caption">
      An example route map. During a race, participants don't see the map. It is
      revealed to everyone once the race ends.
    </p>
  </section>

  <section class="section">
    <SectionTitle>In-Game</SectionTitle>
    <p>
      During a race, a compact <strong>overlay</strong> sits in the corner of
      your screen, no need to alt-tab. It shows your race name, in-game time,
      current zone, progression, tier, and death count at a glance. The overlay
      also lists your available exits so you always know where you can go next.
      Below it, a <strong>live leaderboard</strong>
      tracks every participant's position in real time.
    </p>
    <p>
      Zone progression is <strong>tracked automatically</strong> through fog
      gates: walk through one and the server knows exactly where you are. The
      live leaderboard shows <strong>time gaps</strong> between players, zone by zone.
    </p>
    <div class="screenshot-container">
      <a href="/screenshots/ingame.png" target="_blank">
        <img
          src="/screenshots/ingame.png"
          alt="SpeedFog Racing in-game overlay showing leaderboard and progression"
          class="screenshot"
        />
      </a>
    </div>
    <p class="screenshot-caption">
      The in-game overlay during a race. Leaderboard, progression, exits, and
      IGT, all visible without leaving the game.
    </p>
  </section>

  <p class="cta">
    Want to know more? Check the <a href="/help">Help &amp; Game Rules</a> page.
  </p>
</main>

<style>
  .about {
    max-width: 800px;
    width: 100%;
    box-sizing: border-box;
    margin: 0 auto;
    padding: 2rem;
  }

  /* Hero */
  .about-hero {
    text-align: center;
    padding: 2rem 0 1rem;
  }

  .about-hero h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
    margin: 0 0 0.75rem;
  }

  .about-hero p {
    color: var(--color-text-secondary);
    font-size: clamp(0.9rem, 2vw, 1.1rem);
    margin: 0;
  }

  /* Sections */
  .section {
    margin-top: 3rem;
  }

  .section p {
    color: var(--color-text-secondary);
    line-height: 1.7;
    margin: 0 0 1rem;
  }

  /* Steps */
  .steps {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .step {
    display: flex;
    gap: 1rem;
    align-items: flex-start;
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    padding: 1.25rem;
  }

  .step-number {
    flex-shrink: 0;
    width: 2rem;
    height: 2rem;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-gold);
    color: var(--color-bg);
    font-weight: 700;
    border-radius: 50%;
    font-size: var(--font-size-sm);
  }

  .step strong {
    display: block;
    color: var(--color-text);
    margin-bottom: 0.25rem;
  }

  .step p {
    margin: 0;
    font-size: var(--font-size-sm);
  }

  /* Route map demo */
  .dag-demo {
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    overflow-x: auto;
    overflow-y: hidden;
    min-width: 0;
    -webkit-overflow-scrolling: touch;
  }

  .dag-demo :global(.zoomable-container) {
    min-height: 0;
  }

  .dag-caption {
    font-size: var(--font-size-sm);
    font-style: italic;
    color: var(--color-text-disabled);
    text-align: center;
  }

  /* Screenshots */
  .screenshot-container {
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    overflow: hidden;
    margin: 1rem 0 0.5rem;
  }

  .screenshot {
    width: 100%;
    height: auto;
    display: block;
  }

  .screenshot-caption {
    font-size: var(--font-size-sm);
    font-style: italic;
    color: var(--color-text-disabled);
    text-align: center;
    margin-top: 0.25rem;
  }

  /* Feature cards */
  .feature-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem;
  }

  .feature-card {
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    padding: 1.25rem;
  }

  .feature-card strong {
    display: block;
    color: var(--color-text);
    margin-bottom: 0.5rem;
  }

  .feature-card p {
    margin: 0;
    font-size: var(--font-size-sm);
  }

  /* CTA */
  .cta {
    text-align: center;
    margin-top: 3rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .cta a {
    color: var(--color-gold);
    text-decoration: none;
  }

  .cta a:hover {
    text-decoration: underline;
  }

  @media (max-width: 640px) {
    .about {
      padding: 1rem;
    }

    .section {
      margin-top: 2rem;
    }

    .feature-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
