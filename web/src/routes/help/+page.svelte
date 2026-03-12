<script lang="ts">
	import MetroDag from '$lib/dag/MetroDag.svelte';
	import heroSeed from '$lib/data/hero-seed.json';

	let openDetails = $state<Set<string>>(new Set());
	let activePool = $state('standard');

	function toggleDetail(id: string) {
		const next = new Set(openDetails);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		openDetails = next;
	}

	function isOpen(id: string): boolean {
		return openDetails.has(id);
	}

	const pools: Record<
		string,
		{
			label: string;
			duration: string;
			pitch: string;
			layers: string;
			legacyDungeons: number;
			majorBosses: number;
			finalTier: number;
			startingRunes: string;
			bossRandomization: string;
			curve: string;
			carePackage: string;
			notes: string[];
		}
	> = {
		standard: {
			label: 'Standard',
			duration: '~1h',
			pitch: 'The balanced format. Good variety of zones, fair resources, straightforward difficulty curve.',
			layers: '25–30',
			legacyDungeons: 2,
			majorBosses: 8,
			finalTier: 18,
			startingRunes: '100k',
			bossRandomization: 'Minor bosses only',
			curve: 'Linear',
			carePackage: 'Catalysts, talismans, spells',
			notes: []
		},
		sprint: {
			label: 'Sprint',
			duration: '~30min',
			pitch: 'Short and fast. Fewer layers, quicker to the final boss. Great for warmups or time-limited sessions.',
			layers: '10–15',
			legacyDungeons: 1,
			majorBosses: 3,
			finalTier: 10,
			startingRunes: '100k',
			bossRandomization: 'Minor bosses only',
			curve: 'Linear',
			carePackage: 'Catalysts, talismans, spells',
			notes: []
		},
		chill: {
			label: 'Chill',
			duration: '~1h',
			pitch:
				'Generous resources and a late difficulty spike. More legacy dungeons to explore, easier item drops. Good entry point.',
			layers: '25–30',
			legacyDungeons: 3,
			majorBosses: 5,
			finalTier: 10,
			startingRunes: '150k',
			bossRandomization: 'All bosses shuffled',
			curve: 'Late spike',
			carePackage: 'Weapons, shields, catalysts, talismans, spells',
			notes: ['Extra Golden Seeds and Sacred Tears']
		},
		hardcore: {
			label: 'Hardcore',
			duration: '~1h',
			pitch:
				'Scarce resources, early difficulty spike, high boss density. No whetblades, minimal care package. You earn everything.',
			layers: '25–30',
			legacyDungeons: 1,
			majorBosses: 12,
			finalTier: 28,
			startingRunes: '50k',
			bossRandomization: 'Minor bosses only',
			curve: 'Early spike',
			carePackage: 'Minimal (catalysts only)',
			notes: ['No whetblades', 'Gargoyles not nerfed']
		},
		boss_shuffle: {
			label: 'Boss Shuffle',
			duration: '~1h',
			pitch:
				'Same structure as Standard, but every boss is randomized — majors included. You never know what awaits behind the fog.',
			layers: '25–30',
			legacyDungeons: 2,
			majorBosses: 8,
			finalTier: 18,
			startingRunes: '100k',
			bossRandomization: 'All bosses shuffled',
			curve: 'Linear',
			carePackage: 'Catalysts, talismans, spells',
			notes: []
		}
	};
</script>

<svelte:head>
	<title>How to Play – SpeedFog Racing</title>
</svelte:head>

<main class="help">
	<header class="help-hero">
		<h1>How to Play</h1>
		<p>Everything you need to play, organize, or cast a SpeedFog race.</p>
	</header>

	<!-- TABLE OF CONTENTS -->
	<nav class="toc">
		<a href="#quick-start" class="toc-card">
			<strong>Quick Start</strong>
			<span>Get playing in minutes</span>
		</a>
		<a href="#game-rules" class="toc-card">
			<strong>Game Rules</strong>
			<span>Map, zones, bosses, victory</span>
		</a>
		<a href="#game-modes" class="toc-card">
			<strong>Game Modes</strong>
			<span>Standard, Sprint, Chill, Hardcore...</span>
		</a>
		<a href="#during-the-race" class="toc-card">
			<strong>During the Race</strong>
			<span>Overlay, tracking, leaderboard</span>
		</a>
		<a href="#faq" class="toc-card">
			<strong>FAQ</strong>
			<span>Common questions answered</span>
		</a>
		<a href="#organizing" class="toc-card">
			<strong>Organizing</strong>
			<span>Create and manage races</span>
		</a>
		<a href="#casting" class="toc-card">
			<strong>Casting</strong>
			<span>Spectate and stream races</span>
		</a>
		<a
			href="https://discord.gg/Qmw67J3mR9"
			class="toc-card toc-card-discord"
			target="_blank"
			rel="noopener noreferrer"
		>
			<strong>Discord</strong>
			<span>Join the community</span>
		</a>
	</nav>

	<!-- ==================== QUICK START ==================== -->
	<section class="section" id="quick-start">
		<h2>Quick Start</h2>

		<p class="pick-path">Log in with Twitch, then pick your path:</p>

		<div class="two-paths">
			<div class="path-card">
				<h3>Race</h3>
				<p class="path-subtitle">Compete against other players</p>
				<ol>
					<li>An organizer sends you an <strong>invite link</strong> — click it to join.</li>
					<li>
						<strong>Download your seed pack</strong> from the race page once seeds are
						released.
					</li>
					<li>Unzip and run <code>launch_speedfog.bat</code>.</li>
					<li>Wait for the organizer to start the race.</li>
				</ol>
			</div>
			<div class="path-card">
				<h3>Solo</h3>
				<p class="path-subtitle">Play right now, at your own pace</p>
				<ol>
					<li>
						Go to <a href="/training"><strong>Solo</strong></a> in the navigation bar.
					</li>
					<li>Pick a <strong>game mode</strong> (pool) and start a session.</li>
					<li><strong>Download</strong> the seed pack.</li>
					<li>Unzip and run <code>launch_speedfog.bat</code>.</li>
					<li>Enjoy!</li>
				</ol>
			</div>
		</div>

		<p class="path-note">
			Solo is the best way to discover SpeedFog. No invite needed, no waiting — just pick a
			mode and go. Your times, deaths, and route maps are saved so you can track your
			progress. You can mark a session as a <em>slow run</em> to exclude it from your stats.
		</p>
	</section>

	<!-- ==================== GAME RULES ==================== -->
	<section class="section" id="game-rules">
		<h2>Game Rules</h2>

		<h3>Starting the Run</h3>
		<p>
			You spawn at the <strong>Chapel of Anticipation</strong>. Your first two exits are the fog
			gate in front of the <strong>Grafted Scion</strong> and the fog on the
			<strong>Roundtable Hold balcony</strong>. The Roundtable Hold is unlocked immediately — you
			can teleport there from the start.
		</p>

		<h3>Starting Equipment</h3>
		<p>
			Every player on the same seed gets <strong>the same starting build</strong>: randomized
			weapons, armor, spells, talismans, key items, runes, and smithing stones. The exact
			care package depends on the <a href="#game-modes">game mode</a>.
		</p>

		<h3>Route Map</h3>
		<p>
			The route map is organized in <strong>layers of increasing difficulty</strong>. Paths can
			<strong>split and merge</strong>, and occasional <strong>cross-links</strong> create
			shortcuts between distant branches. Within a layer, parallel paths have the
			<strong>same difficulty</strong> — only the specific zones differ.
		</p>
		<p>
			Fog gates are <strong>one-way</strong> — you can only walk through them in one direction.
			You can always <strong>fast travel back</strong> to a previous grace if you need to return
			to an earlier zone.
		</p>
		<div class="dag-demo">
			<MetroDag graphJson={heroSeed} />
		</div>
		<p class="dag-caption">
			An example route map. During a race, participants don't see the map — it is revealed once
			the race ends.
		</p>

		<h3>Zones &amp; Enemies</h3>
		<p>
			Zones include mini dungeons, legacy dungeons, and boss arenas. Enemy difficulty
			<strong>scales with zone depth</strong>. Item and enemy locations are
			<strong>randomized</strong> — stat requirements are removed, so you can use
			<strong>any weapon regardless of stats</strong>. Weapons found in the world are
			automatically upgraded to match your progression.
		</p>

		<h3>Bosses</h3>
		<p>
			All players face the <strong>same number of bosses</strong> on balanced parallel paths.
			Bosses drop <strong>weapons, talismans, Golden Seeds, and Sacred Tears</strong>. Whether
			bosses are shuffled depends on the <a href="#game-modes">game mode</a>.
		</p>
		<h3>Victory</h3>
		<p>
			All paths converge toward a single <strong>final boss</strong> — a random major boss
			(Radagon, Malenia, Mohg, Radahn...) that changes with every seed. Defeat it to finish.
			Your time is recorded via <strong>in-game timer (IGT)</strong>, which pauses during
			loading screens, death animations, and menus.
		</p>

		<!-- Accordion: Race rules -->
		<button
			class="accordion"
			class:open={isOpen('rules')}
			aria-expanded={isOpen('rules')}
			onclick={() => toggleDetail('rules')}
		>
			<span>Race rules</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('rules')}
			<div class="panel">
				<ul>
					<li><strong>Glitchless</strong> — no glitch exploits allowed</li>
					<li>
						<strong>No quit-outs</strong> — don't close the game to manipulate state
					</li>
					<li>
						<strong>No LiveSplit</strong> — IGT is tracked automatically by the mod
					</li>
					<li>
						<strong>No other mods</strong> — only SpeedFog, no additional modifications
					</li>
					<li><strong>Skips are allowed</strong> — creative routing is fair game</li>
				</ul>
			</div>
		{/if}

		<!-- Accordion: Tips -->
		<button
			class="accordion"
			class:open={isOpen('tips')}
			aria-expanded={isOpen('tips')}
			onclick={() => toggleDetail('tips')}
		>
			<span>Tips</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('tips')}
			<div class="panel">
				<ul>
					<li><strong>Kalé</strong> has moved to the Roundtable Hold.</li>
					<li>
						<strong>Merchants</strong> from the open world are relocated inside the
						zones — keep an eye out, they can have useful gear.
					</li>
					<li>
						After defeating <strong>Radahn</strong>, make sure to activate the grace or
						you won't be able to progress to the next zone.
					</li>
				</ul>
			</div>
		{/if}
	</section>

	<!-- ==================== GAME MODES ==================== -->
	<section class="section" id="game-modes">
		<h2>Game Modes</h2>
		<p>
			Each mode uses a different seed pool with its own balance of duration, difficulty, and
			resources. <strong>Standard</strong> is the default — other modes twist the formula.
		</p>

		<div class="pool-container">
			<div class="pool-tabs">
				{#each Object.entries(pools) as [key, pool]}
					<button
						class="pool-tab"
						class:active={activePool === key}
						onclick={() => (activePool = key)}
					>
						{pool.label}
						<span class="pool-tab-duration">{pool.duration}</span>
					</button>
				{/each}
			</div>

			{#each Object.entries(pools) as [key, pool]}
				{#if activePool === key}
					<div class="pool-card">
						<p class="pool-pitch">{pool.pitch}</p>
						<div class="pool-grid">
							<div class="pool-stat">
								<span class="pool-stat-label">Layers</span>
								<span class="pool-stat-value">{pool.layers}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Legacy Dungeons</span>
								<span class="pool-stat-value">{pool.legacyDungeons}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Major Bosses</span>
								<span class="pool-stat-value">{pool.majorBosses}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Final Tier</span>
								<span class="pool-stat-value">{pool.finalTier}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Starting Runes</span>
								<span class="pool-stat-value">{pool.startingRunes}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Boss Shuffle</span>
								<span class="pool-stat-value">{pool.bossRandomization}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Difficulty Curve</span>
								<span class="pool-stat-value">{pool.curve}</span>
							</div>
							<div class="pool-stat">
								<span class="pool-stat-label">Care Package</span>
								<span class="pool-stat-value">{pool.carePackage}</span>
							</div>
						</div>
						{#if pool.notes.length > 0}
							<ul class="pool-notes">
								{#each pool.notes as note}
									<li>{note}</li>
								{/each}
							</ul>
						{/if}
					</div>
				{/if}
			{/each}
		</div>
	</section>

	<!-- ==================== DURING THE RACE ==================== -->
	<section class="section" id="during-the-race">
		<h2>During the Race</h2>

		<div class="overlay-layout">
			<div class="overlay-text">
				<h3>In-Game Overlay</h3>
				<p>
					A compact overlay sits in the corner of your screen — no need to alt-tab. It
					shows your current zone, in-game time, tier, death count, progression, and a
					live leaderboard with all participants.
				</p>

				<h3>Zone Tracking</h3>
				<p>
					Your progress is tracked <strong>automatically</strong> as you walk through fog
					gates — no manual action needed. The mod detects fog gate traversals and reports
					them to the server, which updates the leaderboard in real time.
				</p>
			</div>
			<div class="overlay-screenshot">
				<div class="screenshot-container">
					<img
						src="/screenshots/overlay-ingame.png"
						alt="SpeedFog Racing in-game overlay"
						class="screenshot"
					/>
				</div>
				<p class="screenshot-caption">
					The in-game overlay during a race.
				</p>
			</div>
		</div>

		<!-- Accordion: Gap timing -->
		<button
			class="accordion"
			class:open={isOpen('gap-timing')}
			aria-expanded={isOpen('gap-timing')}
			onclick={() => toggleDetail('gap-timing')}
		>
			<span>Gap timing explained</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('gap-timing')}
			<div class="panel">
				<p>
					The leaderboard shows <strong>time gaps</strong> relative to the leader's pace
					on each layer — similar to LiveSplit splits.
				</p>
				<ul>
					<li>
						<strong style="color: var(--color-success)">Green</strong> = you entered
						this layer faster than the leader did
					</li>
					<li>
						<strong style="color: var(--color-danger)">Red</strong> = you entered this
						layer slower
					</li>
				</ul>
				<p>
					The gap is fixed when you enter a layer (based on entry time difference). It
					only starts growing in real time if you exceed the leader's time budget for that
					layer.
				</p>
			</div>
		{/if}

		<!-- Accordion: Keyboard shortcuts -->
		<button
			class="accordion"
			class:open={isOpen('shortcuts')}
			aria-expanded={isOpen('shortcuts')}
			onclick={() => toggleDetail('shortcuts')}
		>
			<span>Keyboard shortcuts</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('shortcuts')}
			<div class="panel">
				<ul>
					<li><kbd>F9</kbd> — Toggle the overlay on/off</li>
					<li><kbd>F10</kbd> — Toggle the leaderboard on/off</li>
				</ul>
			</div>
		{/if}

		<!-- Accordion: Overlay settings -->
		<button
			class="accordion"
			class:open={isOpen('overlay-settings')}
			aria-expanded={isOpen('overlay-settings')}
			onclick={() => toggleDetail('overlay-settings')}
		>
			<span>Overlay settings</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('overlay-settings')}
			<div class="panel">
				<p>
					Go to <a href="/settings"><strong>Settings</strong></a> to customize the
					in-game overlay before downloading your seed pack:
				</p>
				<ul>
					<li><strong>Overlay size</strong> — adjust the scale to fit your resolution</li>
					<li><strong>Zone language</strong> — display zone names in your language</li>
					<li><strong>Tips language</strong> — in-game tips in your language</li>
				</ul>
				<p>
					These settings are baked into your seed pack — change them before downloading.
				</p>
			</div>
		{/if}
	</section>

	<!-- ==================== FAQ ==================== -->
	<section class="section" id="faq">
		<h2>FAQ</h2>

		<h3>Gameplay</h3>

		<button
			class="accordion"
			class:open={isOpen('faq-respec')}
			aria-expanded={isOpen('faq-respec')}
			onclick={() => toggleDetail('faq-respec')}
		>
			<span>Can I respec?</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-respec')}
			<div class="panel">
				<p>
					Yes. You start with Larval Tears and can respec at any Site of Grace (no need to
					find Rennala).
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-smithing')}
			aria-expanded={isOpen('faq-smithing')}
			onclick={() => toggleDetail('faq-smithing')}
		>
			<span>Where do I get smithing stones?</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-smithing')}
			<div class="panel">
				<p>
					All smithing stones are available at the Roundtable Hold shop in unlimited stock
					from the start. Weapons found in the world are automatically upgraded to match
					your progression.
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-igt')}
			aria-expanded={isOpen('faq-igt')}
			onclick={() => toggleDetail('faq-igt')}
		>
			<span>How does IGT work?</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-igt')}
			<div class="panel">
				<p>
					IGT (In-Game Time) is Elden Ring's internal timer. It ticks while you play, and
					pauses during loading screens, death animations, and menus. Deaths increment a
					counter but don't add to your time.
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-solo-vs-race')}
			aria-expanded={isOpen('faq-solo-vs-race')}
			onclick={() => toggleDetail('faq-solo-vs-race')}
		>
			<span>What's the difference between Solo and Racing?</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-solo-vs-race')}
			<div class="panel">
				<p>Same game, different context:</p>
				<ul>
					<li>
						<strong>Solo</strong> — you play alone, at your own pace. No opponents, no
						waiting. The route map is visible from the start. Seeds aren't consumed, so
						you can practice as much as you want.
					</li>
					<li>
						<strong>Racing</strong> — synchronized start, live leaderboard, route map
						hidden until the race ends. Competitive results recorded.
					</li>
				</ul>
			</div>
		{/if}

		<h3>Troubleshooting</h3>

		<button
			class="accordion"
			class:open={isOpen('faq-antivirus')}
			aria-expanded={isOpen('faq-antivirus')}
			onclick={() => toggleDetail('faq-antivirus')}
		>
			<span>Windows Defender blocks the mod</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-antivirus')}
			<div class="panel">
				<p>
					The mod injects into Elden Ring's process, which antivirus software can flag as
					suspicious. This is expected behavior for game mods. Allow the file in Windows
					Defender (or your antivirus) and re-run <code>launch_speedfog.bat</code>.
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-stale')}
			aria-expanded={isOpen('faq-stale')}
			onclick={() => toggleDetail('faq-stale')}
		>
			<span>"SEED OUTDATED" message</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-stale')}
			<div class="panel">
				<p>
					The organizer changed the seed after you downloaded. Go back to the race page
					and download the new zip.
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-overlay')}
			aria-expanded={isOpen('faq-overlay')}
			onclick={() => toggleDetail('faq-overlay')}
		>
			<span>Overlay not showing</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-overlay')}
			<div class="panel">
				<p>
					Press <kbd>F9</kbd> to toggle it. If that doesn't work, make sure you launched
					with <code>launch_speedfog.bat</code> (not the regular game shortcut).
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-disconnect')}
			aria-expanded={isOpen('faq-disconnect')}
			onclick={() => toggleDetail('faq-disconnect')}
		>
			<span>Lost connection during a race</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-disconnect')}
			<div class="panel">
				<p>
					The mod reconnects automatically. Your progress is not lost — the server replays
					any missed zone events on reconnect.
				</p>
			</div>
		{/if}

		<button
			class="accordion"
			class:open={isOpen('faq-abandon')}
			aria-expanded={isOpen('faq-abandon')}
			onclick={() => toggleDetail('faq-abandon')}
		>
			<span>I got auto-abandoned — why?</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('faq-abandon')}
			<div class="panel">
				<p>
					If your IGT doesn't change for 15 minutes (game closed, stuck, or AFK), the
					server marks you as abandoned. The race can finish once all participants are done
					or abandoned.
				</p>
			</div>
		{/if}

	</section>

	<!-- ==================== ORGANIZING ==================== -->
	<section class="section" id="organizing">
		<h2>Organizing a Race</h2>

		<ol>
			<li>
				Click <strong>Create Race</strong> from the navigation bar.
			</li>
			<li>
				Choose a name, select a <strong>game mode</strong> (seed pool), and configure
				options: participate yourself or organize only, schedule a time, set public or private
				visibility.
			</li>
			<li>
				<strong>Invite players</strong> — send them an invite link from the race page.
			</li>
			<li>
				<strong>Release seed packs</strong> — typically ~10 minutes before start. Players
				can then download and install.
			</li>
			<li>
				When everyone is ready, click <strong>Start Race</strong>. All connected players are
				notified in-game.
			</li>
		</ol>

		<div class="lifecycle">
			<div class="lifecycle-step">
				<strong>Setup</strong>
				<p>Invite players, release seed packs when ready.</p>
			</div>
			<span class="lifecycle-arrow">&rarr;</span>
			<div class="lifecycle-step">
				<strong>Running</strong>
				<p>Live tracking and leaderboard active.</p>
			</div>
			<span class="lifecycle-arrow">&rarr;</span>
			<div class="lifecycle-step">
				<strong>Finished</strong>
				<p>Results and full route map revealed.</p>
			</div>
		</div>

		<!-- Accordion: Seed management -->
		<button
			class="accordion"
			class:open={isOpen('orga-seeds')}
			aria-expanded={isOpen('orga-seeds')}
			onclick={() => toggleDetail('orga-seeds')}
		>
			<span>Seed management &amp; reroll</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('orga-seeds')}
			<div class="panel">
				<p>
					A seed is assigned when you create the race. You can <strong>reroll</strong> to
					get a different seed as long as you haven't released the seed packs yet. Once
					packs are released and players have downloaded, the seed is locked.
				</p>
				<p>
					If you reroll after someone downloaded, their mod will show a
					<strong>"SEED OUTDATED"</strong> banner — they'll need to re-download.
				</p>
			</div>
		{/if}

	</section>

	<!-- ==================== CASTING ==================== -->
	<section class="section" id="casting">
		<h2>Casting &amp; Spectating</h2>

		<h3>Spectators</h3>
		<p>
			Anyone can open a race page and watch live. During setup, the route map is
			<strong>hidden</strong> to avoid spoilers. Once the race is running, spectators see the
			<strong>full route map</strong> with real-time player positions, zone progression, and
			<strong>time gaps</strong> between players.
		</p>

		<h3>Casters</h3>
		<p>
			Casters have <strong>full route map visibility at all times</strong> — including during
			setup. This lets streamers prepare and commentate the race live. Anyone can request
			the caster role from the race page, or the organizer can add them.
		</p>

		<!-- Accordion: OBS overlays -->
		<button
			class="accordion"
			class:open={isOpen('cast-obs')}
			aria-expanded={isOpen('cast-obs')}
			onclick={() => toggleDetail('cast-obs')}
		>
			<span>OBS overlays</span>
			<span class="chevron"></span>
		</button>
		{#if isOpen('cast-obs')}
			<div class="panel">
				<p>
					The race page has an <strong>OBS Overlays</strong> button with Browser Source
					URLs. Two overlays are available:
				</p>
				<ul>
					<li>
						<strong>Route map</strong> — live metro map with player positions
						(recommended: 800 x 600). Supports auto-follow mode.
					</li>
					<li>
						<strong>Leaderboard</strong> — ranked standings with progression and IGT
						(recommended: 400 x 800).
					</li>
				</ul>
				<p>
					Both use a <strong>transparent background</strong> and work as OBS Browser
					Sources. Also available for solo sessions.
				</p>
			</div>
		{/if}
	</section>
</main>

<style>
	.help {
		max-width: 760px;
		width: 100%;
		box-sizing: border-box;
		margin: 0 auto;
		padding: 2rem;
		scroll-behavior: smooth;
	}

	/* Hero */
	.help-hero {
		text-align: center;
		padding: 1.5rem 0 0.5rem;
	}

	.help-hero h1 {
		font-size: clamp(1.5rem, 4vw, 2.25rem);
		font-weight: 700;
		color: var(--color-gold);
		margin: 0 0 0.5rem;
	}

	.help-hero p {
		color: var(--color-text-secondary);
		font-size: clamp(0.9rem, 2vw, 1.1rem);
		margin: 0;
	}

	/* TOC */
	.toc {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
		gap: 0.6rem;
		margin-top: 1.75rem;
	}

	.toc-card {
		display: block;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 0.85rem 1rem;
		text-decoration: none;
		border: 1px solid transparent;
		transition:
			background 0.15s ease,
			border-color 0.15s ease;
	}

	.toc-card:hover {
		background: var(--color-surface-elevated);
		border-color: var(--color-gold);
	}

	.toc-card strong {
		display: block;
		color: var(--color-gold);
		font-size: var(--font-size-sm);
		margin-bottom: 0.15rem;
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
		margin: 0 0 1rem;
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
		font-size: var(--font-size-sm);
	}

	.section ul,
	.section ol {
		color: var(--color-text-secondary);
		line-height: 1.7;
		margin: 0 0 0.75rem;
		padding-left: 1.5rem;
		font-size: var(--font-size-sm);
	}

	.section li {
		margin-bottom: 0.25rem;
	}

	.section li strong {
		color: var(--color-text);
	}

	/* Two paths */
	p.pick-path {
		text-align: center;
		margin: 0 0 0.75rem;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
	}

	.two-paths {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
	}

	.path-card {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
		border: 1px solid var(--color-border);
	}

	.path-card h3 {
		margin: 0 0 0.15rem;
		font-size: var(--font-size-lg);
		color: var(--color-gold);
	}

	.path-card .path-subtitle {
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
		margin: 0 0 0.75rem;
	}

	.path-card ol {
		margin: 0;
		padding-left: 1.25rem;
		font-size: var(--font-size-sm);
	}

	.path-card li {
		margin-bottom: 0.35rem;
	}

	p.path-note {
		text-align: center;
		margin-top: 1rem;
		font-style: italic;
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
	}

	/* DAG demo */
	.dag-demo {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		overflow-x: auto;
		overflow-y: hidden;
		min-width: 0;
		-webkit-overflow-scrolling: touch;
		margin: 1rem 0 0.5rem;
	}

	.dag-demo :global(.zoomable-container) {
		min-height: 0;
	}

	p.dag-caption {
		font-size: var(--font-size-xs);
		font-style: italic;
		color: var(--color-text-disabled);
		text-align: center;
	}

	/* Pool container — tabs + card as one unit */
	.pool-container {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	/* Pool tabs */
	.pool-tabs {
		display: flex;
		background: var(--color-surface);
		border-bottom: 1px solid var(--color-border);
	}

	.pool-tab {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.1rem;
		padding: 0.6rem 0.5rem;
		background: var(--color-surface);
		border: none;
		border-right: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
	}

	.pool-tab:last-child {
		border-right: none;
	}

	.pool-tab:hover {
		color: var(--color-text);
		background: var(--color-surface-elevated);
	}

	.pool-tab.active {
		background: var(--color-surface-elevated);
		color: var(--color-gold);
		box-shadow: inset 0 -2px 0 var(--color-gold);
	}

	.pool-tab-duration {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
	}

	.pool-tab.active .pool-tab-duration {
		color: var(--color-text-secondary);
	}

	/* Pool card */
	.pool-card {
		background: var(--color-surface-elevated);
		padding: 1.25rem;
	}

	.pool-card .pool-pitch {
		color: var(--color-text);
		font-size: var(--font-size-sm);
		margin: 0 0 1rem;
	}

	.pool-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
		gap: 0.6rem;
	}

	.pool-stat {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.pool-stat-label {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.pool-stat-value {
		font-size: var(--font-size-sm);
		color: var(--color-text);
		font-weight: 500;
	}

	ul.pool-notes {
		margin: 0.85rem 0 0;
		padding-left: 1.25rem;
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
	}

	ul.pool-notes li {
		margin-bottom: 0.1rem;
	}

	/* Overlay two-column layout */
	.overlay-layout {
		display: grid;
		grid-template-columns: 1fr 280px;
		gap: 1.5rem;
		align-items: start;
	}

	.overlay-text h3:first-child {
		margin-top: 0;
	}

	/* Screenshots */
	.screenshot-container {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	.screenshot {
		width: 100%;
		height: auto;
		display: block;
	}

	p.screenshot-caption {
		font-size: var(--font-size-xs);
		font-style: italic;
		color: var(--color-text-disabled);
		text-align: center;
		margin-top: 0.25rem;
	}

	/* Accordion */
	.accordion {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 0.75rem 1rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
		margin-top: 0.5rem;
		text-align: left;
	}

	.accordion:hover {
		border-color: var(--color-purple);
		color: var(--color-purple-hover);
	}

	.accordion.open {
		border-color: var(--color-gold);
		border-bottom-color: transparent;
		border-bottom-left-radius: 0;
		border-bottom-right-radius: 0;
	}

	.chevron {
		display: inline-block;
		width: 0.45rem;
		height: 0.45rem;
		border-right: 2px solid currentColor;
		border-bottom: 2px solid currentColor;
		transform: rotate(45deg);
		transition: transform var(--transition);
		flex-shrink: 0;
	}

	.accordion.open .chevron {
		transform: rotate(-135deg);
	}

	/* Panel */
	.panel {
		background: var(--color-surface);
		border: 1px solid var(--color-gold);
		border-top: none;
		border-bottom-left-radius: var(--radius-md);
		border-bottom-right-radius: var(--radius-md);
		padding: 1rem 1.25rem;
		margin-bottom: 0.25rem;
	}

	.panel p {
		color: var(--color-text-secondary);
		line-height: 1.7;
		margin: 0 0 0.75rem;
		font-size: var(--font-size-sm);
	}

	.panel p:last-child {
		margin-bottom: 0;
	}

	.panel ul {
		margin: 0 0 0.75rem;
		padding-left: 1.25rem;
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		line-height: 1.7;
	}

	.panel ul:last-child {
		margin-bottom: 0;
	}

	.panel li {
		margin-bottom: 0.2rem;
	}

	.panel strong {
		color: var(--color-text);
	}

	kbd {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		font-family: var(--font-family);
		font-size: var(--font-size-xs);
		color: var(--color-text);
	}

	code {
		background: var(--color-surface-elevated);
		padding: 0.1rem 0.35rem;
		border-radius: var(--radius-sm);
		font-size: 0.85em;
		color: var(--color-gold);
	}

	/* Lifecycle */
	.lifecycle {
		display: flex;
		align-items: stretch;
		gap: 0.5rem;
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

	/* Responsive */
	@media (max-width: 640px) {
		.help {
			padding: 1rem;
		}

		.section {
			margin-top: 2rem;
		}

		.two-paths {
			grid-template-columns: 1fr;
		}

		.pool-tab {
			font-size: var(--font-size-xs);
			padding: 0.5rem 0.25rem;
		}

		.pool-grid {
			grid-template-columns: 1fr 1fr;
		}

		.overlay-layout {
			grid-template-columns: 1fr;
		}

		.lifecycle {
			flex-direction: column;
		}

		.lifecycle-arrow {
			text-align: center;
			transform: rotate(90deg);
			font-size: var(--font-size-base);
		}
	}
</style>
