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
			<span>Care package, items, bosses, scaling, victory</span>
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
			<span>Live route map, caster role</span>
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
			You spawn at the <strong>Chapel of Anticipation</strong>. From there, you walk through
			your first fog gate. The <strong>Roundtable Hold</strong> is unlocked immediately — you
			can teleport there from the start.
		</p>

		<h3>Care Package</h3>
		<p>
			At the beginning of each run, you receive a randomized starting build: weapons, shields,
			catalysts, armor, talismans, sorceries, incantations, and crystal tears. The care package
			is determined by the seed — everyone in the same race gets the exact same build.
		</p>
		<p>
			Weapons come pre-upgraded (typically +12 standard / +5 somber). You also receive all
			whetblades so every weapon affinity is available from the start.
		</p>

		<h3>Key Items</h3>
		<p>
			To prevent softlocks, all key items are given at the start of the run:
		</p>
		<ul>
			<li>Academy Glintstone Key, Drawing-Room Key, all DLC access keys</li>
			<li>All Great Runes (restored, equippable at graces)</li>
			<li>3 extra Talisman Pouches (4 talisman slots total)</li>
			<li>Lantern (hands-free light)</li>
			<li>Larval Tears for respec at any Site of Grace</li>
		</ul>

		<h3>Starting Resources</h3>
		<ul>
			<li>~100,000 runes (as Lord's Rune consumables)</li>
			<li>Golden Seeds and Sacred Tears to upgrade your flasks</li>
		</ul>

		<h3>Smithing Stones</h3>
		<p>
			All smithing stones (normal and somber, every tier) are available for purchase at the
			Roundtable Hold shop with unlimited stock. Upgrading costs only one stone per level.
		</p>

		<h3>Route Map Structure</h3>
		<p>
			The route map is organized in layers of increasing difficulty. As you progress deeper
			through the fog gates, you encounter harder zones and tougher enemies. Every parallel
			path through the map has the same structure: same length, same difficulty.
		</p>
		<p>
			Zones include mini dungeons (caves, catacombs, tunnels), legacy dungeons (Stormveil,
			Raya Lucaria...), boss arenas, and major boss encounters.
		</p>

		<h3>Enemies and Bosses</h3>
		<p>
			Enemy difficulty scales with the depth of each zone in the route map.
			Basic enemies and wildlife are randomized between zones of similar difficulty,
			but <strong>bosses always stay in their original arena</strong> — the route map
			determines which boss you face, but once you step through the fog gate into a boss
			arena, the fight is the vanilla encounter.
		</p>

		<h3>Items</h3>
		<p>
			Item locations are randomized. Stat requirements are removed — you can use any weapon
			regardless of your stats. Weapons found in the world are automatically upgraded to
			match your current level.
		</p>

		<h3>Victory Condition</h3>
		<p>
			The race ends when you defeat the final boss. The final boss varies with each seed —
			it can be any major boss in the game (Radagon, Malenia, Mohg, Radahn, etc.). The
			in-game timer (IGT) records your finish time.
		</p>
	</section>

	<!-- PLAYING -->
	<section class="section" id="playing">
		<h2>Playing a Race</h2>

		<h3>Requirements</h3>
		<ul>
			<li>Elden Ring (PC, latest version)</li>
			<li>A Twitch account (for authentication)</li>
			<li>An invitation from a race organizer</li>
		</ul>

		<h3>Joining a Race</h3>
		<ol>
			<li>Log in with Twitch on the SpeedFog Racing website.</li>
			<li>The organizer adds you to the race.</li>
			<li>From the race page, download your seed pack — a personalized zip file with
				everything you need.</li>
			<li>Extract the seed pack into your Elden Ring mod folder.</li>
			<li>Launch the game. The mod connects automatically to the race server.</li>
		</ol>

		<h3>During the Race</h3>
		<p>
			Once the organizer starts the race, create a new character and begin. The in-game
			overlay shows:
		</p>
		<ul>
			<li>Race name and your in-game time (IGT)</li>
			<li>Your current progression tier and death count</li>
			<li>A live leaderboard with all participants</li>
		</ul>
		<p>
			Your progress is tracked automatically as you walk through fog gates. No manual
			action is needed — just play.
		</p>
	</section>

	<!-- TRAINING -->
	<section class="section" id="training">
		<h2>Training Mode</h2>
		<p>
			Training mode lets you practice solo runs on fresh seeds without joining a race.
			No account is required — anyone can start a training session.
		</p>
		<ol>
			<li>Go to the <a href="/training">Training</a> page.</li>
			<li>Pick a pool (different durations and settings are available).</li>
			<li>Download the seed pack and install it like a regular race.</li>
			<li>Play at your own pace — the route map is visible after you start.</li>
		</ol>
		<p>
			Training sessions are a great way to get familiar with the format, the care package
			system, and the fog gate navigation before entering a competitive race.
		</p>
	</section>

	<!-- ORGANIZING -->
	<section class="section" id="organizing">
		<h2>Organizing a Race</h2>

		<h3>Creating a Race</h3>
		<ol>
			<li>Click <strong>Create Race</strong> from the navigation bar.</li>
			<li>Choose a name, select a seed pool, and configure options.</li>
			<li>The race starts in <strong>Draft</strong> status — only you can see it.</li>
		</ol>

		<h3>Race Lifecycle</h3>
		<div class="lifecycle">
			<div class="lifecycle-step">
				<strong>Draft</strong>
				<p>Add or remove participants and casters. Configure settings.</p>
			</div>
			<span class="lifecycle-arrow">&rarr;</span>
			<div class="lifecycle-step">
				<strong>Open</strong>
				<p>Participants can download their seed packs and connect.</p>
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

		<h3>Seed Pools</h3>
		<p>
			Seeds are pre-generated in pools with different settings. Each pool has a target
			duration and difficulty level. When you create a race, you pick a pool — the
			server assigns a fresh seed from that pool.
		</p>
	</section>

	<!-- CASTING -->
	<section class="section" id="casting">
		<h2>Casting &amp; Spectating</h2>

		<h3>Spectators</h3>
		<p>
			Anyone can open a race page and watch the race live. The route map updates in
			real time, showing each player's current position and progression.
		</p>

		<h3>Casters</h3>
		<p>
			Casters are a special role assigned by the organizer. Unlike regular spectators,
			casters have full visibility of the route map during the race — it is not blurred
			for them. This is designed for streamers who want to commentate and analyze
			the race live.
		</p>
		<p>
			If you are casting, ask the race organizer to add you as a caster before the race
			starts.
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
		align-items: flex-start;
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
