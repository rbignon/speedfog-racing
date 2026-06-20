# Changelog

All notable changes to SpeedFog Racing are documented in this file.

## [1.15.0] - 2026-06-18

### Rewards

- New **Speedfrog** green name style and a Frog badge, granted the first time you finish a race or daily seed
- New **Daily Winner** badge for everyone who placed 1st on at least one daily seed during the past week

### Seeds

- Removed the useless "Shadow Realm Blessing" entry from the Site of Grace menu: the DLC blessing submenu it opens is irrelevant in SpeedFog, since enemies are scaled by fog tiers rather than Scadutree leveling
- Reduced the weight of Leonine Misbegotten
- Zone cluster weights rebalanced from production data

### Daily Seed

- Redesigned the "Play now" button

### Website

- Seed packs now download natively through the browser, with progress, ETA, and resume support, instead of being buffered in memory
- Reworker about and help pages
- Removed the Beta badge from the site
- Added an easter egg

## [1.14.0] - 2026-06-13

### Seeds

- Removed the Caelid Guardian Golem from the boss pool
- Lowered the chance of Promised Consort Radahn (PCR) or Radabeast being picked as the final boss
- The default maximum number of parallel paths is now 3 (was 4)

### Mod

- The Elden Ring 1.12+ menu input delay is now removed by a dedicated DLL (`MenuInputDelayFix.dll`) bundled in every seed pack

## [1.13.0] - 2026-06-07

### Seeds

- **UWYG Boss Rush**: Rykard is no longer part of the boss rush
- Reduced the weight of the Volcano Manor stretch reached after Godskin Noble
- Six bosses downgraded to minor: Ancestor Spirit, Dryleaf Dane (Leda fight), Ancient Dragon-Man, Elemer of the Briar, Devonia, and Jori Elder Inquisitor
- Two outgoing fog gates from the same node can share a proximity group again: with balanced parallel branches, adjacent gates now create genuine path divergence between players instead of forcing everyone toward the nearest one
- Exclude DLC mausoleums from candidate arenas

### Modes

- Each mode can now define its own rules, shown as a **Mode Rules** section in the seed download window and in a quick popover on the mode's settings card

### Races

- Fix: the no-show timeout now waits for the late-join window to close before abandoning early registrants, so someone who registered ahead of an open window is no longer swept before it elapses

### Mod Overlay

- Fixed the leaderboard "+ N more" footer: when you rank outside the top 9 in a large race, it now counts only the players hidden below your row instead of also counting those already represented by the "…" separator
- The seed-mismatch banner now also fires mid-session: if a daily seed is rerolled while you are already running, the overlay flags your loaded seed pack as stale instead of noticing only at the next connection

## [1.12.0] - 2026-06-01

### Daily Seed

- Daily seeds now award points: finishing a daily scores points out of **100** based on your rank in the field, so a perfect week tops out at **700**.
- New weekly leaderboard: points add up across the week's daily seeds, with a Daily / Week toggle on the daily page to switch between a single day's standings and the running weekly totals
- The weekly champion(s) are now decided by total weekly points instead of by most first-place finishes
- Qualified abandoners earn points too: you score as long as you got past the first fog gate

### Seeds

- Demi-Human boss arenas are now classified as small
- New mode: **UWYG Boss Rush**, an "Use What You Get" linear boss rush

## [1.11.1] - 2026-05-28

### Seeds

- Fia's Champions downgraded to a minor boss
- Parallel branches in the same graph layer now have closer weights, so sibling paths have more comparable durations

### Mod

- Support for Elden Ring 1.16.2

## [1.11.0] - 2026-05-28

### Seeds

- Removed the vanilla Stake of Marika at Mohg and Astel, which could respawn the player outside the boss arena and softlock the run
- Hardcore mode: Lamenter's Gaol keys are now part of the item pool, Gargoyles nerfed

### Races

- Quit-outs are now allowed by the rules

### Stats

- New weapons tracking: the mod reports your equipped weapons (one or two hands) every second, attributed to the zone you are in
- Race leaderboard rows show the dominant weapon combos used by each participant, with a popover detailing the top combos and their share of time played
- Metro map node popups show the dominant weapon combo used in that zone across the field
- New "Weapons" tab on the stats page

## [1.10.2] - 2026-05-22

### Seeds

- Lightning Divine Warrior is now a regular boss instead of a major boss
- Dragon bosses disallowed in additional arenas
- Darklight and Scorpion catacombs: only main entrances are used as spawn points
- Zone weights rebalanced so parallel paths at the same depth have closer durations
- Aging Untouchables can now be damaged without parrying them

### Races

- Public races now require a scheduled start time

### Training

- Removed the "Slow run" option

## [1.10.1] - 2026-05-20

### Seeds

- Volcano Hallway: exit fog gates restricted
- Crucible Knight Duo removed from the boss pool
- Dragon bosses can no longer spawn in arenas that are too small for them

### Mod Overlay

- Visual refresh: overlay now follows the SpeedFog graphic charter
- Fix: reloading a stale save mid-session could leave a finish flag set in game memory, preventing a fresh run from ever firing its finish. The mod now detects save reloads and flushes per-save flag state

## [1.10.0] - 2026-05-17

### Seeds

- New zones added:
  - Nokron
  - Pre-Nokron
  - Ainsel River start
  - Main Ainsel River
  - Deeproot Depths
  - Stone Coffin Fissure
  - Ancient Ruins of Rauh
- Haligtree and Elphael downgraded to mini dungeons
- Minor elite ennemies removed:
  - Lobster
  - Large Bigmouth Imp
  - Golden Leonine Misbegotten
  - Omen
  - One of the Fire Knights
  - One of the Smith Golems
- Boss Rush: major-boss pool size per generation reduced from 15 to 12 so the pool is no longer exhausted near the end of the graph and silently replaced by minor bosses, yielding a more balanced run
- Multi-phase bosses are no longer swapped between them
- When several paths converge on the same node, the merge now reuses a single canonical entry fog gate, preserving that node's exit capacity
- Fix: two outgoing fog gates from a single node can no longer share a proximity group, so parallel branches actually spread across the area instead of clustering on adjacent gates
- Fix: many previously inert candidates (Rugalea, Death Rite Bird Charos, and ~70 others) now appear as minor bosses

### Item Randomizer

- Sacred Flask Upgrades (Golden Seeds, Sacred Tears) now spawn on major bosses, DLC revered spirit locations and DLC forges rewards
- Removed drop of useless key items: Rusty Key, Academy Glintstone Key, both Dectus medallion halves, both Haligtree Secret medallion halves, and the Hole-Laden Necklace

### Daily Seed

- Reaching a 14-day daily streak now permanently grants a new Molten Aura phantom skin

## [1.9.0] - 2026-05-14

### Daily Seed

- New daily streak system: a counter of consecutive qualifying days on the daily, displayed alongside the daily week grid and on your profile next to a best-streak high score
- Eligibility: a daily counts toward your streak as soon as you make it past the first fog gate. You don't have to finish, abandoning after reaching the second zone still credits the day; registering without playing or skipping the daily entirely does not
- Freezes catch missed days automatically before the streak breaks. You earn one every 7 consecutive qualifying days, capped at 2 in stock; each missed day consumes one. With both saved you can miss up to two days in a row before the streak resets

## [1.8.0] - 2026-05-12

### Daily Seed

- Live projected leaderboard in the in-game overlay during daily races: replays from earlier runners are projected against your current IGT and pushed once per second, so you always see where you stand

### Seeds

- New exit-driven seed generator: every fog gate of a given zone is routed to a zone of the next depth, up to the number of zones available at that depth, yielding more varied connections
- Improved weight balancing between zones at the same depth, so parallel paths have closer durations
- Boss Rush mode: more major bosses and up to 3 parallel paths per depth
- Removed Colossal Fingercreeper from the boss pool
- Removed Farum Azula Temple as a possible legacy dungeon
- Item Randomizer: boss scale and phase HP options are now set explicitly

### Races

- Fixed a stale-save bypass that could grant an unintended finish when reloading a save with a finish flag already set

### Rewards

- Weathered name template recolored to a warm bronze

## [1.7.1] - 2026-05-07

### Daily Seed

- Week-grid navigation on the daily pages, with inline prev/next controls and bounded earlier nav
- Disable inactivity monitor on daily seeds

### Seeds

- Removed the balcony above Godskin Duo
- Reverted the loader from ME3 back to ModEngine 2, because of intermittent in-game stutters

### Stats

- New stats cards on /dashboard and /user/[username], with a weekly activity series

## [1.7.0] - 2026-05-02

### Rewards

- New rewards system: badges and name templates, equipped from /settings and shown in chat, leaderboard, profile, and the in-game overlay
- Phantom skins: equip a cosmetic phantom aura that shows on your character in-game and on your avatar on the website

### Daily Seed

- New Daily Seed feature: a fresh seed every day, shared by everyone

### Races

- Late-join window: auto-finish is held off during the window, and the no-show cutoff is scoped per participant

### Seeds

- Add Haligtree Town as a legacy dungeon
- Stormveil's barred gate is now open at startup
- Boss arena fixes: Vaillant Gargoyles excluded from two-phase arenas
- Tuned arena and boss sizes
- Sprint pools now include only remembrance bosses as final ones
- Migrated from ModEngine 2 to ME3
- SpeedFog now ships with a Linux launcher alongside the Windows one

## [1.6.0] - 2026-04-22

### Races

- Late-join mode: organizers can keep registration open after the race starts. Running races show an "Open" badge with a deadline countdown and a Join button in the sidebar
- Auto-end: organizers can set a maximum race duration, after which the race automatically finalizes and any unfinished runners are marked as abandoned

### Seeds

- Boss randomization now respects arena compatibility (thanks to Ignite's [Boss Arena Randomizer](https://github.com/ignitesouls/BossArenaRandomizer))
- Updated list of elite enemies used as minor bosses
- Ancestor Spirit reclassified as a minor boss
- Fia's Champions can't be in a two phase arena anymore (fuck you)
- Drop-in entrances into major boss arenas are no longer used as a major boss (e.g. Red Wolf of Radagon)
- Hardcore mode: minor bosses are now randomized
- Hardcore mode: care package removed
- Varied run-complete messages

### In-game

- Race-ends countdown in the overlay, with a warning color when under 30 minutes remaining

### Website

- Rich link previews: race pages now generate a dynamic social image, with scheduled times shown in the organizer's timezone
- Pool selection replaced by a compact tab bar on the training and race creation pages
- Pool settings card simplified
- Zones stats window shortened to 30 days to better reflect the current meta

## [1.5.10] - 2026-04-16

### Seeds

- Minor boss randomization: add elite ennemies:
  - Colossal Fingercreeper
  - Crucible Knights (including Devonia)
  - Divine Bird Warriors (Lightning, Frost and Wind)
  - Elder Lion
  - Fire Knights
  - Fire Prelates
  - Giant Death Crab
  - Guardian Golem
  - Hornsent
  - Lobster
  - Omen
  - Runebear
  - Smith Golem
- Divine Beast Dancing Lion and Basilisks excluded from minor boss randomization
- Patches excluded from boss candidates

### In-game

- Fix: leaderboard now keeps the "ready" / "registered" label for pre-launch players once the race starts, instead of switching to a misleading "1/N" layer count

## [1.5.9] - 2026-04-15

### Seeds

- New mode: Boss Rush, made exclusively of boss arenas and major bosses, no legacy dungeons or mini dungeons
- Most major boss arenas can now be used as pass-through path candidates (their entry can serve as an exit), increasing topology variety
- Redmane Castle boss excluded from candidates, as it can be missing when the Radahn festival is active
- Chill mode: minor bosses are now randomized and swapped between each other
- Rebalanced final boss probabilities
- Bloodstain height reduced for better in-world readability

### Website

- Renamed "pool" to "mode" and "layer" to "depth" across the UI

## [1.5.8] - 2026-04-10

### Seeds

- Boss arenas now lock their exits when entered, making it impossible to skip a boss by walking through without engaging it
- More boss arenas can serve as pass-through path candidates, since exit restrictions are no longer needed to prevent skips

### In-game

- Death markers now appear only at exit fog gates, focusing the visual signal on where it best indicates zone difficulty
- Fix: prevent state desync after network blips

## [1.5.7] - 2026-04-07

### Seeds

- Bosses in multi-boss fights are now swapped between each other on Boss Shuffle, Expedition, Sprint, and Standard pools
- Chill seeds now feature more major bosses and fewer mini dungeons
- Arena size is now taken into account when randomizing bosses
- Recalibrated zone weights from observed race data (797 participants, 153 seeds)
- Rebalanced item distribution: reduce ashes of war to 35, added staves, seals, shields and 51 melee weapons
- Sainted Hero's Grave excluded from mini dungeon candidates
- Well Depths Key and Hole-Laden Necklace removed from guaranteed key items
- Seeds now always branch when only one path exists, improving topology variety
- Fix: Gideon can no longer be skipped via side exits in his arena
- Fix: save file backup no longer interferes with Elden Ring's autosave during compression

### Website

- Welcome panel now shows gameplay tips, Sprint is pre-selected and marked "Recommended" on the training page for new players
- Improved race creation form defaults and UX
- Redesigned pool settings display on race pages
- System messages now appear in public chat when a player finishes or abandons
- Fix: personal highlights (Speed Demon, Zone Wall) now compare against the runner-up instead of the mean, reducing false positives
- Fix: seed reroll now properly broadcasts the updated race state

### Performance

- Multiple server and database optimizations for higher spectator concurrency

## [1.5.6] - 2026-04-04

### Chat

- Dual-channel chat: racers coordinate in a private Participants channel during the race, then unlock Spoilers on finish to discuss freely without spoiling others still playing. Messages are persistent and restored on reconnect

### Seeds

- Mimic Tear and Ancestor Spirit classified as major bosses
- Castle Sol now uses its main entrance only
- Godskin Duo arena restricted to front left exit
- Bayle's arena entry can no longer be used as an exit
- Grafted Scion boss arena entry can no longer be used as an exit
- Leyndell Colosseum no longer grouped with Gideon entrances on the bedroom cluster
- Standard pool rebalanced: more major bosses (10, up from 8), fewer mini dungeons (6, down from 8)

### Website

- The website URL is now [https://speedfog.racing](https://speedfog.racing)

## [1.5.5] - 2026-04-01

### Stats

- Fixed systematic ELO deflation that unfairly penalized active players
- New players now calibrate faster with adaptive K factor during their first 10 races
- Zone and boss stats count abandoned runs as backtracks at the player's last visited location

### In-game

- Grace sit animation is now faster
- Standup animation is now instant

### Website

- Seed reporting: re-rolling a seed now lets you flag it as buggy with an optional reason
- Improved personal highlight detection (Boss Slayer, Clean Streak, Lead Lost)

## [1.5.4] - 2026-03-31

### Stats

- ELO fairness: rating changes against provisional players are now weighted by their confidence, and race winners can no longer lose ELO

### Seeds

- Fix: Colosseum fogs no longer incorrectly grouped with Godfrey/Gideon fogs in Leyndell

### In-game

- "Heavy door opened" text popup no longer appears when opening doors in catacombs
- Fix: "Repeat warp" grace menu works correctly again for Maliketh

## [1.5.3] - 2026-03-30

### Stats

- Private races are now excluded from ELO calculations

### Seeds

- Starting weapons upgraded to +25 on Expedition, Chill, Sprint, Standard, and Boss Shuffle pools
- Starting runes increased to 40k on Expedition, Sprint, Standard, and Boss Shuffle pools
- Reworked item distribution: ashes of war, and crystal tears now placed at key locations
- Golden Trees and Marika Churches are now key item locations
- Dragonkin Soldier of Nokstella classified as major boss
- Added conflict between Radahn and Redmane Castle boss to reduce the risk of Radahn's festival being active
- Fix: custom weapons with ashes of war now upgrade correctly

### In-game

- Fix: run complete banner no longer replays when warping between zones
- Fix: burning the Erdtree no longer disrupts zone tracking for the rest of the run

### Website

- Open registration visibility: joinable races badge in navbar, "Open" badge and Join button on race cards, "Races to Join" section on dashboard
- Replay Metro map respects player selection filter
- Improved Metro map label contrast for accessibility and @Mitchriz
- Fix: entrance nodes hidden correctly in progressive Metro map visibility

## [1.5.2] - 2026-03-28

### Stats

- ELO revamp: ratings now factor in seed difficulty, field strength, and number of races played, with a confidence badge on the leaderboard.
- Dominant traits use percentile ranking with descriptive labels (e.g. "Top 5% Rusher")

### Seeds

- Runes are awarded directly rather than through Lord's Runes
- Starting runes reduced (Chill: 150k to 100k, others except Hardcore: 100k to 25k)
- Starting class weapons upgraded to +24 on all pools except Hardcore
- Whetstone Knife given on all pools
- Lamenter's Gaol keys removed from Hardcore pools
- Colosseum entrance grouped with Gideon/Goldfrey fogs to prevent adjacent entry/exit pairs
- Snowfield tunnel restricted to its main entrance gate
- Fix: Spirit Calling Bell now correctly usable

### In-game

- Fix: gap timing updates correctly on the last layer when the leader finishes

### Races

- Editable combobox for scheduling race time

## [1.5.1] - 2026-03-26

### Seeds

- Zone weights recalibrated from observed race data (316 participants, 65 seeds), improving run pacing accuracy
- Weight-matched cluster selection: parallel branches now correctly pick zones with similar difficulty, producing more balanced splits

### Races

- Personal highlights on finished race pages: 15 detectors across combat, pathing, and competitive categories surface your standout moments (boss slayer, smart backtrack, comeback, and more)
- Fix: private races now appear in the race listing for participants, organizers, and casters
- Fix: participant list now updates in real-time for spectators when players join or leave during setup

### In-game

- Fresh save validation: the mod rejects stale saves (IGT > 15s) when joining a race or starting a solo session, preventing corrupted zone data. Starting a New Game clears the rejection

### Metro map

- Fix: player trailing paths no longer draw straight lines across the map on backtracks
- Fix: zoomed metro view stays centered on finished players in the OBS overlay instead of switching to full map

## [1.5.0] - 2026-03-25

### Death markers

- Bloodstain visuals now appear at fog gate entrances where other players have died, revealing zone difficulty at a glance. Markers are activated dynamically as deaths occur during the race.

### Seeds

- Fix: Godskin Noble entry can no longer be used as exit, preventing broken paths
- Fix: path splits no longer reuse a cluster already picked by a passant branch

### In-game

- Fix: death marker flags are re-applied after exiting a loading screen
- Fix: overlay now shows IGT instead of a permanent "GO!" message on reconnect

### Races

- Ephemeral race chat: participants can exchange messages during a race via a collapsible sidebar
- Organizer controls moved to a compact toolbar under the DAG
- Open registration and max participants can now be updated after race creation

### Website

- Pool settings card now visible on solo session detail pages
- Various UI polish (OBS button, scrollbars, badges, icons)

## [1.4.4] - 2026-03-22

### Seeds

- Final boss is now selected from a weighted pool instead of uniform random, for better variety across runs
- Sentry's Torch sold at Roundtable Hold on all pools except Hardcore
- Malenia nerfed on Chill seeds
- Minor boss randomization disabled on Hardcore seeds
- Fix: Earthbore Cave boss can no longer use entry as exit, preventing broken paths

### In-game

- Zone reveal now triggers at the end of the loading screen instead of using a suspense countdown

## [1.4.3] - 2026-03-21

### Stats

- Boss stats now show the actual randomized boss name instead of the vanilla boss name
- Multi-phase bosses (e.g. Rennala, Fire Giant) are now tracked with both phase names
- Abandoned races are now included in profile stats, pool stats, and dashboard

### Seeds

- Starting tier set to 3 on all pools (Sprint and Hardcore now match Standard and Chill)
- Legacy dungeons are no longer forced as the first layer on Hardcore seeds
- Fewer final boss candidates on Standard and Hardcore seeds
- Rennala's arena and Midra can no longer serve as through-pass zones, since the boss fight can be skipped
- Royal Ancestor Spirit and Valiant Gargoyles are now classified as major bosses

### In-game

- Overlay now shows the current layer number when backtracking
- Fix: zone reveal delay was sometimes bypassed, briefly showing the next zone early

## [1.4.2] - 2026-03-19

### Stats

- New global stats page with ELO leaderboard, zone analytics, boss analytics, and play styles
- ELO rating system with margin-of-victory scoring
- 7 behavioral traits: Rusher, Cautious, Explorer, Pathfinder, Boss Slayer, Resilient, Rage Quitter
- Play style traits on user profiles, ELO rating in profile header
- Zone stats: deadliest, most backtracked, slowest, and fastest zones
- Boss stats: kill rates, average deaths, and backtrack ratios for major bosses
- Players with fewer than 3 completed races are hidden as provisional

### Seeds

- Save backup system: seed packs now include an automatic backup daemon and recovery scripts for Windows and Linux
- Convergence and fallback zone selection uses weighted random picks for more even type distribution across the map
- More boss arenas (Morgott, Hoarah Loux, Godskin Noble, Gaius, Romina) can now serve as split points, since entry fog gates can also be used as exits
- New proximity groups for Stranded Graveyard and Shadow Keep Storehouse elevator fogs
- Maximum parallel paths reduced from 4 to 3 on Hardcore seeds

## [1.4.1] - 2026-03-18

### Seeds

- Margit and Morgott can no longer both appear in the same run
- Sewer barred gates in Subterranean Shunning-Grounds are now opened at game start
- Proximity groups for Leyndell, Academy, and Farum Azula prevent entry/exit pairs from using adjacent fog gates
- Mohgwyn Palace added to the generation pool
- Spirit Calling Bell given as a starting item, enabling spirit ash summoning from the start
- Fix: tiers no longer regress between layers
- Fix: recently-split branches no longer get immediately consumed by a rebalance on an unrelated branch
- Fix: rebalancing now works with 2 parallel paths (merge-first strategy), producing better-paced maps
- Fix: crosslinks now work through sequences of boss arenas
- Fix: vanilla Stake of Marika at Radahn no longer causes a softlock by respawning outside the DAG

### Races

- Inactivity timeout increased from 15 to 30 minutes
- Sprint Final now measures time spent on the final boss specifically, instead of summing all final-tier zones

### Solo

- New expedition pool for long runs (~5h, 90-100 layers)
- Discord notification when starting a solo run while live on Twitch

### In-game

- Fix: zone detection after death no longer incorrectly backtracks to an adjacent zone

### Metro map

- Fix: large DAGs (100+ layers) are now readable with dynamic max zoom

## [1.4.0] - 2026-03-14

### Seeds

- Starting tier raised from 1 to 3 on Standard and Chill
- Maximum parallel paths reduced from 4 to 3
- Sprint pool expanded with more bosses and a higher final tier
- Maps have fewer long linear stretches: branches are now more evenly spaced with automatic rebalancing
- 5 new zones added to the generation pool: Castle Morne, Dragon's Pit, Scadu Altus Catacombs, and Shadow Keep West Rampart
- Cross-links can now reuse entry fog gates, creating more shortcut opportunities
- Boss Shuffle: the final boss is now also randomized (a bug causing instant deaths on multi-phase bosses has been fixed)
- Fix: zone detection completely reworked: fog gate tracking is now significantly more reliable

### In-game

- Fix: gap timing no longer shows gaps larger than your own play time when entering a zone late
- Fix: gap timing no longer jumps to +0:00 when falling behind the leader's pace

### Website

- New changelog page: view all updates directly on the website
- Help page redesigned as "How to Play"
- Difficulty curve now shown in pool settings
- Fix: login link on the race detail page now works correctly

## [1.3.5] - 2026-03-09

### Seeds

- Care package expanded: weapon pool grows from 18 to 43 weapons covering all categories, armor pool from 6 to 15 pieces per slot with light/medium/heavy options
- Final tier rebalanced across pools: Chill and Sprint lowered from 12 to 10, Standard from 20 to 18
- Fix: generated maps no longer exceed the configured maximum layer count
- Fix: seed discard now processes all pools instead of only the first one

### Races

- Seed pack can now be downloaded while the race is running, not just during setup
- Fix: scheduled time now shows "To be defined" instead of being hidden when no time is set

### In-game

- Fix: backtracking through fog gates is now properly detected. Event flags are cleared after capture so the game can re-trigger them on revisit
- Fix: ambiguous zone detection after death or remembrance now picks the most recently visited zone instead of an arbitrary candidate

### Metro map

- Fix: player path lines no longer draw straight lines across the map after a teleport. Paths now break at teleport gaps

### Website

- Fix: abandoned players now see the full metro map instead of the fog-of-war view

## [1.3.4] - 2026-03-06

### Seeds

- Boss randomization now supports 3 levels: none, minor bosses only, or all bosses (previously just on/off)
- Minor boss randomization enabled on all pools except Chill; Boss Shuffle pool now randomizes all bosses including major ones
- Rusty Key added to starting items, no more Gostoc detour at Stormveil
- All crafting recipes unlocked from the start
- Smithing stones, gloveworts, and crafting materials are now randomized
- Talismans, notable weapons, and crystal tears now appear at seedtree, church, and cross locations
- Fix: somber smithing stone shop prices now match normal weapon upgrade costs
- Fix: cross-links no longer connect zones that are too close together geographically
- Fix: multi-zone boss clusters no longer leave broken exits

### Races

- Countdown (10→1→GO!) at race start
- At least 2 participants required to start a race

### In-game

- Fix: phantom path lines no longer appear on the overlay after fast-travel or teleport
- Fix: zone detection after loading screens is now more reliable

### Metro map

- Layer number displayed in the node popup

## [1.3.3] - 2026-03-03

### Seeds

- New "Chill" pool for relaxed races: generous starting resources, gentler difficulty curve, and more legacy dungeons
- Difficulty scaling tuned per pool: Chill eases you in with a gentle plateau, Hardcore ramps up sharply in the endgame
- Boss and mini dungeon proportions adjusted, zones limited to 2 entrances max
- Fix: legacy dungeon zones now show location names instead of boss names (e.g. "Academy of Raya Lucaria after Red Wolf" instead of "Red Wolf of Radagon")
- Maps can now split and merge independently, so wider splits no longer force faster convergence

### Solo

- OBS metro map overlay for solo training sessions, so streamers can now show their training runs in OBS
- Cancelled and abandoned sessions are now distinct: sessions where you never connected are marked as cancelled and excluded from your solo run counter

### Streaming

- OBS metro map overlay font size can be set via URL parameter for easier readability tuning

### In-game

- Fix: gap timing for other players no longer jumps every second in the overlay
- Fix: zone tracking no longer conflicts with item spawn flags on seeds with 100+ connections
- Fix: backtracking via death or teleport now correctly records zone history

### Website

- Settings onboarding banner for new users pointing to language and overlay options
- Highlight selection improved with more varied results and community highlights prioritized over individual ones
- Fix: nodes no longer clipped at edges in follow mode
- Fix: duplicate zones no longer appear across highlight cards

### Translations

- Improved French translations with proper contractions and elision rules (e.g. "de Astel" → "d'Astel")
- Fix: exit fog gate descriptions now use the correct text variant

## [1.3.2] - 2026-02-28

### Logic

- Zone history now tracks backtracking: when a player returns to a previously visited zone, time and deaths are correctly attributed to each visit instead of being lumped with the wrong zone
- Players who don't connect within 15 minutes of race start are automatically abandoned, and the race auto-finishes if all remaining players are done

### Seeds

- Cross-links enabled on all pools: fog gates can now connect distant branches, creating shortcuts and more route variety
- Standard pool now requires at least 2 legacy dungeons per seed

### Streaming

- Casters can self-join a race with a "Cast this race" button, no need for the organizer to add them manually
- LIVE badge on the leaderboard and caster list for participants and casters currently streaming on Twitch

### In-game

- Gap timer now freezes when you finish or when the race ends, instead of continuing to tick
- Fix: players on the same zone are now sorted by who arrived first instead of total IGT
- Fix: gap timing for other players updates smoothly in real-time instead of jumping on each server update

### Website

- Fix: time spent now shows correctly for abandoned players in the zone popup
- Fix: Discord notifications are now sent when a race auto-finishes due to all players abandoning

## [1.3.1] - 2026-02-27

### Logic

- Cross-links between DAG branches: fog gates can now connect parallel paths, creating alternate routes and more interesting race decisions
- Final boss candidates restricted to Remembrance bosses across all pools

### Solo

- Mark a solo session as a "slow run" to exclude it from your performance stats, useful for casual runs, testing, or practice sessions

### In-game

- LiveSplit-style gap timing in the leaderboard overlay: gaps stay fixed while within the leader's pace, then grow in real-time when falling behind. Gaps ahead of the leader's pace are shown in green, gaps behind in red

### Metro map

- Zone click popup on the race replay: click any node during replay to see entrance/exit details and visitor stats
- Fix: abandoned players no longer orbit endlessly on the race replay

### Streaming

- OBS overlay configuration panel: set max leaderboard lines and enable auto-follow for the DAG overlay
- Live player dots on the DAG overlay during a running race
- Follow mode for the DAG overlay: the camera automatically tracks player progression with trailing paths
- During setup, the DAG overlay now shows the real map structure (labels hidden) so streamers can position their OBS overlay before the race starts

## [1.3.0] - 2026-02-26

### Logic

- Zone weights recalibrated from production race data, so run lengths are now more balanced and predictable
- Traversal constraints prevent degenerate seeds where entry and exit fog gates are right next to each other (Stormveil, Academy, Haligtree, etc.)
- Multi-zone boss areas where the boss can be skipped (e.g. Ashen Leyndell) are no longer treated as mandatory boss encounters
- Boss zone weights now use a phase-based system (multi-phase bosses like Rennala, Messmer, Fire Giant count double) instead of timing data
- Fix: zone tracking could resolve to an unexplored zone on death or fast travel
- Fix: shared exit fog gates no longer silently drop event flag registrations, fixing ~40% of seed build failures
- Fix: 3 DLC key items (Hole-Laden Necklace, Well Depths Key, Messmer's Kindling) excluded from randomization, fixing 60% of remaining seed build failures
- Fix: Sealing Tree zone tracking no longer breaks due to a vanilla event flag conflict
- Fix: Fissure preboss zone excluded from clustering to prevent broken paths

### Seeds

- Boss zone names now consistently show the boss name (e.g. "Leyndell - Godfrey" instead of "Leyndell - Erdtree Sanctuary")
- All minor boss types (Miniboss, Night Miniboss, Dragon Miniboss, Evergaol) now swap with each other in Boss Shuffle mode
- Hostile NPCs now randomize among themselves instead of being left in their original positions
- Training pools aligned with their race counterparts
- Pool settings now display stonesword keys and gargoyle poison status
- Maps can now branch into up to 4 parallel paths (previously 3), producing wider and more varied race maps
- Split probability increased across all pools, so race maps now branch much more frequently, reducing long linear stretches

### Solo

- Ghost replay: watch previous participants' runs on the training map as animated ghosts
- Start and end datetimes now shown on training detail page

### Races

- F1-style gap timing in the leaderboard overlay: each player sees their time gap to the leader, using split times for running players and final time delta for finished players
- Players can now abandon a running race via a "Rage quit" button on the race page
- Inactive players (IGT unchanged for 5 minutes) are automatically abandoned
- Add to calendar button (Google, Apple, Outlook) on scheduled race pages
- Discord bot integration: scheduled events are automatically created and synced with the race lifecycle, and @Runner is mentioned on race creation
- DNF players are now sorted by progression (furthest first) instead of arbitrary order

### In-game

- Your own entry is always visible in the leaderboard overlay, even when the board is full
- During setup phase, the overlay shows participant status (ready/not ready) instead of progress
- Fix: ready status now uses orange to match the website leaderboard colors

### Website

- Finished race cards now show the winner's name and avatar
- Recent results section added to the homepage
- Player search bar in the navigation bar
- Fix: profile links on leaderboard player names now work correctly

### Translations

- 40+ new French translations for full coverage
- Entrance text and exit labels are now translated on the metro map
- Fix: possessive patterns now match zone names with or without "'s"

## [1.2.0] - 2026-02-23

### Logic

- Completely reworked seed generation algorithm: zones are now selected cluster-first, producing more varied and balanced paths
- 5 additional major boss correctly integrated: Hoarah-Loux, Gideon, Placidusax, Putrescent Knight, and Rennala
- Radagon/Elden Beast is now a valid final boss. The Erdtree warp now correctly forces Maliketh's defeat, preventing the softlock where Erdtree thorns blocked access
- Major bosses with a single fog gate (Messmer, Malenia, Bayle, etc.) can now appear as pass-through zones mid-run, not just as final boss dead-ends
- Great Runes are now pre-activated at the start of a run to prevent a softlock at Fia's Champions
- Fix: zone tracking could resolve to an unexplored zone on death or fast travel

### Seeds

- 6 Stonesword Keys given as starting items
- Miquella's Cross locations can now contain key items and flask upgrades
- Training pools aligned with their race counterparts

### Race Replay

- Animated race replay on the metro map: watch all participants progress through the map in real time
- Playback controls: play/pause, speed adjustment, and seekbar
- Player tokens show skulls on death and a crown for the winner
- Toggle between the static map and the animated replay

### Race Highlights

- Automatically generated post-race highlights: fastest zones, closest finishes, death-heavy areas, and more
- Highlights are displayed on the finished race page with interactive links to the relevant zones on the map

### Metro map

- Death skull icons on nodes where players died
- Node popup now shows your own visit stats (time spent, deaths) during a race
- Entrance/exit labels prefixed with "From"/"To" for clarity

### Website

- "Training" mode renamed to "Solo"
- Seed pack download now shows a confirmation modal with rules and installation steps
- Dashboard activity rows show more details and color-coded status
- Game rules section added to the help page

## [1.1.1] - 2026-02-21

### Seeds

- Seedtree and church added as key item placement locations
- Fix: boss arena exits are now pruned from one-way entry zones

### In-game

- Per-zone death tracking with death counter in overlay

### Metro map

- Node popup now displays the randomized boss name
- Entrance fog gate names displayed on connections between zones

### Website

- Dashboard and profile redesign with stat cards and per-pool stats table
- Twitch link on user profile page

## [1.1.0] - 2026-02-20

### Seeds

- New pool "Boss Shuffle": minor and major bosses are randomized, the final boss is still a major boss in its own arena
- All seeds have been discarded and regenerated (4 per pool)
- Improved seed balance: legacy dungeons (Stormveil, Leyndell, Volcano Manor, etc.) no longer disproportionately dominate path weights

### Logic

- Enir-Ilim is now excluded from zones to prevent softlock
- Auriza Side Tomb is now excluded from zone generation (confusing trap-chest dungeon that appeared too frequently)
- The sending gate at Redmane Castle is now ignored as it is only active during the Radahn festival
- Legacy dungeons (Stormveil, Academy, Leyndell, etc.) can now appear as split/merge nodes in the DAG
- Zones unreachable from their entry fogs are now automatically pruned, preventing broken seeds
- To prevent using the same zones as split/merge nodes, two improvements were made:
  - Multiple paths can now lead to the same spawn point in a zone
  - An entrance fog gate in a zone can also serve as an exit

### Races

- When creating a race, the organizer can choose to let players join on their own until the race starts
- Participants can no longer see other participants' zones in the leaderboard
- Your placement and player count now appear on finished race cards in your profile
- Finished races are now sorted by most recent first

### In-game

- New in-game shortcut F10 to toggle the leaderboard
- IGT (In-Game Time) is now frozen when the race is over
- Improved precision when detecting the player's position after a death
- Fix: warp detection after burning the Erdtree in the Fire Giant arena
- Fix: leaderboard not updating until players reached the 2nd zone
- Fix: zone transitions during long loading screens were missed
- Fix: position tracking when revisiting a zone
- Fix: prevent Ashes of War re-spawn on WebSocket reconnect
- Default overlay font size reduced from 32 to 18

### Metro map

- The zone popup now displays how much time was spent in the area

### Website

- More information about seed pools on the website
- You can change the font size of the in-game overlay in the settings page
- Improved date picker for race scheduling

### Translations

- French translation corrections

## [1.0.0] - 2026-02-19

Initial release, first version used in a real race.

### Races

- Race creation with invitations and participant management
- Multiple seed pools: Standard, Sprint, Hardcore
- Seed pack download with organizer-controlled release timing
- Seed re-roll during setup
- Private and public races
- Scheduled races with date/time picker
- Caster role for commentators
- User profile with stats and activity timeline
- Personal dashboard with active sessions and recent activity
- Paginated race listing
- Training mode with anonymous spectator access

### In-game

- Real-time overlay with zone name, IGT, deaths, tier, and leaderboard
- Automatic zone and boss detection via event flags
- Overlay updates on fast travel
- Reliable zone transitions even during long loading screens

### Metro map

- Interactive metro-style visualization of the race path
- Click any node to see fog gate text, exits/entrances, visitors, time spent, and zone deaths
- Click leaderboard players to highlight their path on the map
- Progress line showing your current route
- Animated map on homepage

### Website

- Race pages with lobby, running, and finished state layouts
- Podium for finished races
- Color-coded leaderboard (20-color palette)
- OBS Overlays for streamers
- Help & Game Rules page

### Translations

- French translation of zone names and game data
