<script lang="ts">
	import MetroDag from '$lib/dag/MetroDag.svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { getTwitchLoginUrl } from '$lib/api';
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
			SpeedFog is an Elden Ring mod that replaces every fog gate with a randomized
			connection. Instead of walking through a familiar door into the expected area, each
			gate teleports you somewhere entirely different. The world becomes an unpredictable
			maze.
		</p>
		<p>
			Because the layout changes with every seed, experienced speedrunners and first-time
			explorers are on equal footing. There is no route to memorize — you navigate by
			reading the world itself.
		</p>
	</section>

	<section class="section">
		<h2>How Races Work</h2>
		<div class="steps">
			<div class="step">
				<span class="step-number">1</span>
				<div>
					<strong>Create a race</strong>
					<p>The organizer sets up a race and invites participants.</p>
				</div>
			</div>
			<div class="step">
				<span class="step-number">2</span>
				<div>
					<strong>Join and download your seed pack</strong>
					<p>
						Each participant receives a seed pack — the same randomized world for
						everyone, but no one sees the layout in advance.
					</p>
				</div>
			</div>
			<div class="step">
				<span class="step-number">3</span>
				<div>
					<strong>Race</strong>
					<p>
						Everyone starts at the same time. The mod tracks your progress in
						real time and reports it to the server.
					</p>
				</div>
			</div>
			<div class="step">
				<span class="step-number">4</span>
				<div>
					<strong>Results</strong>
					<p>
						The first player to defeat the final boss wins. The full route map
						is revealed to everyone after the race ends.
					</p>
				</div>
			</div>
		</div>
	</section>

	<section class="section">
		<h2>The Route Map</h2>
		<p>
			Every seed generates a unique map — a network of fog gates connecting areas.
			SpeedFog Racing visualizes this as a metro-style route map, showing how zones
			connect and where each player currently is.
		</p>
		<p>
			Each layer of the map follows a pattern: mini dungeons, legacy dungeons, boss
			arenas, and major bosses. No matter which path you take, you will face the same
			types of challenges at each stage. Enemy scaling also increases as you progress
			deeper into the run, keeping every path equally demanding.
		</p>
		<p>
			The final destination is always a random major boss. Defeat it to finish the race.
		</p>
		<div class="dag-demo">
			<MetroDag graphJson={heroSeed} />
		</div>
		<p class="dag-caption">
			An example route map. During a race, the map is blurred for participants to prevent
			spoilers — it only reveals fully once the race ends.
		</p>
	</section>

	<section class="section">
		<h2>Key Features</h2>
		<div class="feature-grid">
			<div class="feature-card">
				<strong>Balanced Paths</strong>
				<p>
					Every path through the map has the same structure and difficulty. No
					shortcut, no lucky route — only execution matters.
				</p>
			</div>
			<div class="feature-card">
				<strong>Live Spectating</strong>
				<p>
					Spectators can follow the race in real time, watching each player's
					position on the full route map as they progress through the fog.
				</p>
			</div>
			<div class="feature-card">
				<strong>In-Game Leaderboard</strong>
				<p>
					Players see a live leaderboard directly in-game, ranked by progression
					through the map. No need to alt-tab — you always know where you stand.
				</p>
			</div>
		</div>
	</section>
</main>

<style>
	.about {
		max-width: 800px;
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

	/* DAG demo */
	.dag-demo {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		overflow: hidden;
		min-width: 0;
	}

	.dag-caption {
		font-size: var(--font-size-sm);
		font-style: italic;
		color: var(--color-text-disabled);
		text-align: center;
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

	@media (max-width: 480px) {
		.about {
			padding: 1rem;
		}
	}
</style>
