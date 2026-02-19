<svelte:head>
	<title>Help & Game Rules – SpeedFog Racing</title>
</svelte:head>

<main class="help">
	<header class="help-hero">
		<h1>Help &amp; Game Rules</h1>
		<p>Everything you need to know to play, organize, or cast a SpeedFog race.</p>
	</header>

	<!-- TABLE OF CONTENTS -->
	<nav class="toc">
		<a href="#game-rules" class="toc-card">
			<strong>Game Rules</strong>
			<span>Equipment, route map, zones, bosses, tips</span>
		</a>
		<a href="#playing" class="toc-card">
			<strong>Playing a Race</strong>
			<span>Requirements, joining, in-game overlay</span>
		</a>
		<a href="#training" class="toc-card">
			<strong>Training Mode</strong>
			<span>Solo practice runs, no account needed</span>
		</a>
		<a href="#organizing" class="toc-card">
			<strong>Organizing a Race</strong>
			<span>Create, configure, start a race</span>
		</a>
		<a href="#casting" class="toc-card">
			<strong>Casting &amp; Spectating</strong>
			<span>Live route map, caster role, OBS overlays</span>
		</a>
		<a href="https://discord.gg/Qmw67J3mR9" class="toc-card toc-card-discord" target="_blank" rel="noopener noreferrer">
			<strong>Discord</strong>
			<span>Join the community, ask questions</span>
		</a>
	</nav>

	<!-- GAME RULES -->
	<section class="section" id="game-rules">
		<h2>Game Rules</h2>

		<h3>Starting the Run</h3>
		<p>
			You spawn at the <strong>Chapel of Anticipation</strong>. Your first two exits are the
			fog gate in front of the <strong>Grafted Scion</strong> and the fog on the
			<strong>Roundtable Hold balcony</strong>. The Roundtable Hold is unlocked immediately —
			you can teleport there from the start.
		</p>

		<h3>Starting Equipment</h3>
		<p>
			The seed determines a care package — <strong>every player gets the same build</strong>:
		</p>
		<ul>
			<li><strong>Randomized gear</strong>: weapons (+0), shields, catalysts, armor, talismans,
				sorceries, incantations, crystal tears, spirit ashes</li>
			<li><strong>All whetblades</strong> for every weapon affinity</li>
			<li><strong>All key items</strong>: Academy Glintstone Key, Drawing-Room Key, DLC keys,
				all Great Runes (restored), 3 Talisman Pouches (4 slots), Lantern, Torrent</li>
			<li><strong>Larval Tears</strong> — respec at any Site of Grace</li>
			<li><strong>~100,000 runes</strong>, Golden Seeds, Sacred Tears</li>
			<li><strong>All smithing stones</strong> at the Roundtable Hold shop (unlimited stock)</li>
		</ul>

		<h3>Route Map</h3>
		<p>
			The route map is organized in <strong>layers of increasing difficulty</strong>. Every
			parallel path has the <strong>same length and difficulty</strong> — only the specific
			zones differ.
		</p>
		<p>
			Fog gates are <strong>one-way</strong> — once you walk through, you can't go back.
			Fast travel to the previous grace if you need to return.
		</p>

		<h3>Zones</h3>
		<p>
			Zones include mini dungeons, legacy dungeons, and boss arenas. Enemy difficulty
			<strong>scales with zone depth</strong> — basic enemies are randomized between zones of
			similar difficulty. Item locations are <strong>randomized</strong> too: stat requirements
			are removed, so you can use <strong>any weapon regardless of stats</strong>. Weapons
			found in the world are automatically upgraded to match your progression.
		</p>

		<h3>Bosses</h3>
		<p>
			Bosses are <strong>not randomized</strong> — they always stay in their original arena.
			The route map determines which boss you face, but the fight itself is vanilla. This
			avoids double randomization (the route already shuffles encounters), keeps bosses in
			their intended environment, and prevents bugs that occur when bosses are placed outside
			their arena.
		</p>
		<p>
			Bosses drop <strong>weapons, talismans, Golden Seeds, and Sacred Tears</strong>.
		</p>

		<h3>Victory</h3>
		<p>
			The race ends when you <strong>defeat the final boss</strong>. The final boss varies with
			each seed — it can be <strong>any major boss</strong> (Radagon, Malenia, Mohg, Radahn...).
			Your finish time is recorded via <strong>in-game timer (IGT)</strong>.
		</p>

		<h3>Tips</h3>
		<ul>
			<li><strong>Kalé</strong> has moved to the Roundtable Hold.</li>
			<li><strong>Merchants</strong> from the open world are relocated inside the zones — keep
				an eye out, they can have useful gear.</li>
			<li>After defeating <strong>Radahn</strong>, make sure to activate the grace or you
				won't be able to progress to the next zone.</li>
		</ul>
	</section>

	<!-- PLAYING -->
	<section class="section" id="playing">
		<h2>Playing a Race</h2>

		<h3>Requirements</h3>
		<ul>
			<li>Elden Ring (PC, latest version)</li>
			<li>A Twitch account (for authentication)</li>
			<li>An invite link from the race organizer</li>
		</ul>

		<h3>Joining a Race</h3>
		<ol>
			<li><strong>Log in</strong> with Twitch on the SpeedFog Racing website.</li>
			<li>The organizer sends you an <strong>invite link</strong> — click it to join the
				race.</li>
			<li>From the race page, <strong>download your seed pack</strong> — a zip file with
				everything you need.</li>
			<li><strong>Extract</strong> the seed pack into your Elden Ring mod folder.</li>
			<li><strong>Launch the game</strong>. The mod connects automatically to the race
				server.</li>
		</ol>

		<h3>During the Race</h3>
		<p>
			Once the organizer starts the race, create a new character and begin. The
			<strong>in-game overlay</strong> shows:
		</p>
		<ul>
			<li>Race name and your <strong>in-game time (IGT)</strong></li>
			<li>Your current <strong>zone name</strong> and <strong>available exits</strong></li>
			<li>Your <strong>progression tier</strong> and <strong>death count</strong></li>
			<li>A <strong>live leaderboard</strong> with all participants</li>
		</ul>
		<p>
			Your progress is tracked <strong>automatically</strong> as you walk through fog gates —
			no manual action needed, just play.
		</p>
	</section>

	<!-- TRAINING -->
	<section class="section" id="training">
		<h2>Training Mode</h2>
		<p>
			Training mode lets you <strong>practice solo</strong> on fresh seeds without joining a
			race. <strong>No account required</strong> — anyone can start a training session.
		</p>
		<ol>
			<li>Go to the <a href="/training">Training</a> page.</li>
			<li>Pick a <strong>pool</strong> (different durations and difficulty levels).</li>
			<li><strong>Download</strong> the seed pack and install it like a regular race.</li>
			<li>Play at your own pace — the <strong>route map</strong> is visible after you start.</li>
		</ol>
		<p>
			Your sessions are saved — you can review your <strong>progress history</strong>, including
			times, deaths, and route maps from previous runs.
		</p>
	</section>

	<!-- ORGANIZING -->
	<section class="section" id="organizing">
		<h2>Organizing a Race</h2>

		<h3>Creating a Race</h3>
		<ol>
			<li>Click <strong>Create Race</strong> from the navigation bar.</li>
			<li>Choose a name, select a <strong>seed pool</strong>, and configure options:
				<strong>participate</strong> in the race or organize only, set a
				<strong>scheduled time</strong>, choose <strong>public or private</strong>
				visibility.</li>
			<li>The race is created in <strong>Setup</strong> status — invite players and get
				ready.</li>
		</ol>

		<h3>Race Lifecycle</h3>
		<div class="lifecycle">
			<div class="lifecycle-step">
				<strong>Setup</strong>
				<p>Invite participants and casters. Configure settings. Players download seed packs.</p>
			</div>
			<span class="lifecycle-arrow">&rarr;</span>
			<div class="lifecycle-step">
				<strong>Running</strong>
				<p>Race in progress. Live tracking and leaderboard active.</p>
			</div>
			<span class="lifecycle-arrow">&rarr;</span>
			<div class="lifecycle-step">
				<strong>Finished</strong>
				<p>Results and full route map revealed to everyone.</p>
			</div>
		</div>
		<p>
			When everyone is ready, click <strong>Start Race</strong> — all connected players are
			notified in-game. During setup, you can also <strong>re-roll the seed</strong> if
			needed — participants will need to re-download their seed pack.
		</p>

		<h3>Seed Pools</h3>
		<p>
			Seeds are pre-generated in pools with different <strong>target durations</strong> and
			difficulty levels. When you create a race, you pick a pool — the server assigns a fresh
			seed from that pool.
		</p>
	</section>

	<!-- CASTING -->
	<section class="section" id="casting">
		<h2>Casting &amp; Spectating</h2>

		<h3>Spectators</h3>
		<p>
			Anyone can open a race page and watch live. During setup, the route map is
			<strong>blurred</strong> to avoid spoilers. Once the race is running, spectators see the
			<strong>full route map</strong> with real-time player positions and progression.
		</p>

		<h3>Casters</h3>
		<p>
			Casters are a special role assigned by the organizer. Unlike spectators, casters have
			<strong>full visibility of the route map at all times</strong> — including during setup.
			This is designed for streamers who want to prepare and commentate the race live.
		</p>
		<p>
			If you're casting, ask the organizer to add you as a caster before the race starts.
		</p>

		<h3>OBS Overlays</h3>
		<p>
			The race page provides <strong>Browser Source URLs</strong> for OBS Studio — a
			<strong>route map overlay</strong> and a <strong>leaderboard overlay</strong>. Click
			"OBS Overlays" on the race page to get the URLs and recommended sizes.
		</p>
	</section>
</main>

<style>
	.help {
		max-width: 800px;
		width: 100%;
		box-sizing: border-box;
		margin: 0 auto;
		padding: 2rem;
	}

	/* Hero */
	.help-hero {
		text-align: center;
		padding: 2rem 0 1rem;
	}

	.help-hero h1 {
		font-size: clamp(1.5rem, 4vw, 2.25rem);
		font-weight: 700;
		color: var(--color-gold);
		margin: 0 0 0.75rem;
	}

	.help-hero p {
		color: var(--color-text-secondary);
		font-size: clamp(0.9rem, 2vw, 1.1rem);
		margin: 0;
	}

	/* Table of contents */
	.toc {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
		gap: 0.75rem;
		margin-top: 2rem;
	}

	.toc-card {
		display: block;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1rem 1.25rem;
		text-decoration: none;
		transition:
			background 0.15s ease,
			border-color 0.15s ease;
		border: 1px solid transparent;
	}

	.toc-card:hover {
		background: var(--color-surface-hover, rgba(255, 255, 255, 0.06));
		border-color: var(--color-gold);
	}

	.toc-card strong {
		display: block;
		color: var(--color-gold);
		font-size: var(--font-size-sm);
		margin-bottom: 0.25rem;
	}

	.toc-card span {
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
		line-height: 1.4;
	}

	.toc-card-discord strong {
		color: var(--color-purple);
	}

	.toc-card-discord:hover {
		border-color: var(--color-purple);
	}

	/* Sections */
	.section {
		margin-top: 3rem;
	}

	.section h2 {
		font-size: var(--font-size-xl);
		font-weight: 600;
		color: var(--color-gold);
		margin: 0 0 1.5rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid var(--color-border);
	}

	.section h3 {
		font-size: var(--font-size-base);
		font-weight: 600;
		color: var(--color-text);
		margin: 1.5rem 0 0.5rem;
	}

	.section h3:first-of-type {
		margin-top: 0;
	}

	.section p {
		color: var(--color-text-secondary);
		line-height: 1.7;
		margin: 0 0 0.75rem;
	}

	.section ul,
	.section ol {
		color: var(--color-text-secondary);
		line-height: 1.7;
		margin: 0 0 0.75rem;
		padding-left: 1.5rem;
	}

	.section li {
		margin-bottom: 0.25rem;
	}

	/* Lifecycle */
	.lifecycle {
		display: flex;
		align-items: stretch;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin: 1rem 0;
	}

	.lifecycle-step {
		flex: 1;
		min-width: 120px;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1rem;
	}

	.lifecycle-step strong {
		display: block;
		color: var(--color-gold);
		margin-bottom: 0.25rem;
		font-size: var(--font-size-sm);
	}

	.lifecycle-step p {
		margin: 0;
		font-size: var(--font-size-xs);
	}

	.lifecycle-arrow {
		color: var(--color-text-disabled);
		font-size: var(--font-size-xl);
		align-self: center;
		flex-shrink: 0;
	}

	@media (max-width: 640px) {
		.help {
			padding: 1rem;
		}

		.section {
			margin-top: 2rem;
		}

		.lifecycle {
			flex-direction: column;
			align-items: stretch;
		}

		.lifecycle-arrow {
			text-align: center;
			transform: rotate(90deg);
			font-size: var(--font-size-base);
		}
	}
</style>
