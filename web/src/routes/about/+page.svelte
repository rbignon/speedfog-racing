<script lang="ts">
	import MetroDag from '$lib/dag/MetroDag.svelte';
	import heroSeed from '$lib/data/hero-seed.json';
</script>

<svelte:head>
	<title>About – SpeedFog Racing</title>
</svelte:head>

<main class="about">
	<header class="about-hero">
		<h1>How SpeedFog Racing Works</h1>
		<p>Race through a randomized Elden Ring — compete on skill, not memorization.</p>
	</header>

	<section class="section">
		<h2>What is SpeedFog?</h2>
		<p>
			SpeedFog is built on top of the
			<a href="https://www.nexusmods.com/eldenring/mods/3295" target="_blank" rel="noopener noreferrer"
				>Fog Gate Randomizer</a
			>
			by <strong>thefifthmatt</strong> — an Elden Ring mod that replaces every fog gate with
			a randomized connection. Instead of walking through a familiar door into the expected
			area, each gate teleports you somewhere entirely different. The world becomes an
			unpredictable maze.
		</p>
		<p>
			SpeedFog adds structure on top of this chaos: it generates
			<strong>balanced route maps</strong> where every path is equally long and challenging.
			No lucky shortcut — only execution matters.
		</p>
	</section>

	<section class="section">
		<h2>How Races Work</h2>
		<div class="steps">
			<div class="step">
				<span class="step-number">1</span>
				<div>
					<strong>Set up</strong>
					<p>
						An organizer creates a race, adds participants, and optionally assigns
						casters who can spectate with full map visibility.
					</p>
				</div>
			</div>
			<div class="step">
				<span class="step-number">2</span>
				<div>
					<strong>Download and launch</strong>
					<p>
						Each participant downloads a seed pack — just run the executable,
						no setup required. Everyone gets the same randomized world.
					</p>
				</div>
			</div>
			<div class="step">
				<span class="step-number">3</span>
				<div>
					<strong>Race</strong>
					<p>
						Everyone starts at the same time. An in-game overlay tracks your
						progress and shows a live leaderboard — no need to alt-tab.
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
		<h2>The Route Map</h2>
		<p>
			Every seed generates a unique route map — a network of fog gates connecting zones
			across the Lands Between. SpeedFog Racing displays it as a
			<strong>metro-style map</strong> so spectators and casters can follow each player's
			progression in real time.
		</p>
		<p>
			The map is structured in <strong>layers of increasing difficulty</strong>: mini
			dungeons, legacy dungeons, boss arenas, and major bosses. Every parallel path is
			balanced — same length, same challenge. The final destination is always a random
			major boss.
		</p>
		<div class="dag-demo">
			<MetroDag graphJson={heroSeed} />
		</div>
		<p class="dag-caption">
			An example route map. During a race, participants don't see the map — it is revealed
			to everyone once the race ends.
		</p>
	</section>

	<section class="section">
		<h2>In-Game</h2>
		<p>
			During a race, a compact <strong>overlay</strong> sits in the corner of your screen —
			no need to alt-tab. It shows your race name, in-game time, current zone, progression,
			tier, and death count at a glance. The overlay also lists your available exits so you
			always know where you can go next. Below it, a <strong>live leaderboard</strong>
			tracks every participant's position in real time.
		</p>
		<p>
			Zone progression is <strong>tracked automatically</strong> through fog gates — walk
			through one and the server knows exactly where you are. Spectators and casters see
			<strong>time gaps</strong> between players, zone by zone.
		</p>
		<div class="screenshot-container">
			<img
				src="/screenshots/ingame.png"
				alt="SpeedFog Racing in-game overlay showing leaderboard and progression"
				class="screenshot"
			/>
		</div>
		<p class="screenshot-caption">
			The in-game overlay during a race. Leaderboard, progression, exits, and IGT — all
			visible without leaving the game.
		</p>
	</section>

	<section class="section">
		<h2>Key Features</h2>
		<div class="feature-grid">
			<div class="feature-card">
				<strong>Balanced Paths</strong>
				<p>
					Every path through the map has the same structure and difficulty.
					No shortcut, no lucky route — only execution matters.
				</p>
			</div>
			<div class="feature-card">
				<strong>Live Spectating</strong>
				<p>
					Spectators follow the race in real time on the route map. Casters get
					full visibility for streaming, with dedicated OBS overlays.
				</p>
			</div>
			<div class="feature-card">
				<strong>Zone Tracking</strong>
				<p>
					Every fog gate traversal is detected automatically. Spectators
					see real-time zone progression and time gaps between players.
				</p>
			</div>
			<div class="feature-card">
				<strong>Solo Mode</strong>
				<p>
					Play on fresh seeds at your own pace — no account required. Your
					sessions are saved with times, deaths, and route maps.
				</p>
			</div>
			<div class="feature-card">
				<strong>Care Package</strong>
				<p>
					Every run starts with a randomized build: weapons, armor, spells,
					and talismans. Same seed, same build — fair from the first fog gate.
				</p>
			</div>
			<div class="feature-card">
				<strong>Multiple Formats</strong>
				<p>
					Sprint, Standard, or Hardcore — pick a seed pool that fits your
					playstyle. From quick 30-minute runs to punishing gauntlets.
				</p>
			</div>
		</div>
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
		font-size: clamp(1.5rem, 4vw, 2.25rem);
		font-weight: 700;
		color: var(--color-gold);
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

	.section h2 {
		font-size: var(--font-size-xl);
		font-weight: 600;
		color: var(--color-gold);
		margin: 0 0 1rem;
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
