# Changelog

All notable changes to SpeedFog Racing are documented in this file.

## [1.3.2] - 2026-02-28

### Logic

- Zone history now tracks backtracking — when a player returns to a previously visited zone, time and deaths are correctly attributed to each visit instead of being lumped with the wrong zone
- Players who don't connect within 15 minutes of race start are automatically abandoned, and the race auto-finishes if all remaining players are done

### Seeds

- Cross-links enabled on all pools — fog gates can now connect distant branches, creating shortcuts and more route variety
- Standard pool now requires at least 2 legacy dungeons per seed

### Streaming

- Casters can self-join a race with a "Cast this race" button — no need for the organizer to add them manually
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

- Cross-links between DAG branches — fog gates can now connect parallel paths, creating alternate routes and more interesting race decisions
- Final boss candidates restricted to Remembrance bosses across all pools

### Solo

- Mark a solo session as a "slow run" to exclude it from your performance stats — useful for casual runs, testing, or practice sessions

### In-game

- LiveSplit-style gap timing in the leaderboard overlay — gaps stay fixed while within the leader's pace, then grow in real-time when falling behind. Gaps ahead of the leader's pace are shown in green, gaps behind in red

### Metro map

- Zone click popup on the race replay — click any node during replay to see entrance/exit details and visitor stats
- Fix: abandoned players no longer orbit endlessly on the race replay

### Streaming

- OBS overlay configuration panel: set max leaderboard lines and enable auto-follow for the DAG overlay
- Live player dots on the DAG overlay during a running race
- Follow mode for the DAG overlay — the camera automatically tracks player progression with trailing paths
- During setup, the DAG overlay now shows the real map structure (labels hidden) so streamers can position their OBS overlay before the race starts

## [1.3.0] - 2026-02-26

### Logic

- Zone weights recalibrated from production race data — run lengths are now more balanced and predictable
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
- Split probability increased across all pools — race maps now branch much more frequently, reducing long linear stretches

### Solo

- Ghost replay: watch previous participants' runs on the training map as animated ghosts
- Start and end datetimes now shown on training detail page

### Races

- F1-style gap timing in the leaderboard overlay — each player sees their time gap to the leader, using split times for running players and final time delta for finished players
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
- Radagon/Elden Beast is now a valid final boss — the Erdtree warp now correctly forces Maliketh's defeat, preventing the softlock where Erdtree thorns blocked access
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

Initial release — first version used in a real race.

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
