# Changelog

All notable changes to SpeedFog Racing are documented in this file.

## [Unreleased]

### Seeds

- Boss placement tracking: randomized boss names are now captured in graph.json
- Entrance fog gate names added to graph.json nodes for visualization
- Seedtree and church added as key item placement locations
- Fix: prune boss_arena exits from one-way entry zones
- Fix: entity ID overflow on DLC bosses

### In-game

- Per-zone death tracking with zone death counter in overlay

### Metro map

- Node popup now displays the randomized boss name
- Entrance texts displayed on DAG connections
- Visitor columns aligned with CSS grid in node popup

### Website

- Dashboard and profile redesign with 4 stat cards and per-pool stats table
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
- Custom DateTimePicker for race scheduling

### Tools

- Parallel seed generation with --jobs flag
- Per-seed timing and summary table

### Translations

- French translation corrections

## [1.0.0] - 2026-02-19

Initial release — first version used in a real race.

### Platform

- FastAPI async server with SQLAlchemy 2.0 and Twitch OAuth
- SvelteKit 5 frontend with runes
- Rust game mod (DLL injection into Elden Ring)

### Races

- Race creation, invitations, and participant management
- Seed pool system with multiple pools (Standard, Sprint, Hardcore)
- Seed pack generation and download
- Seed release workflow: organizer controls when participants can download
- Seed re-roll during setup
- Private race support (is_public flag)
- Scheduled races
- Caster role for spectators
- User profile page with stats and activity timeline
- Personal dashboard with active sessions and recent activity
- Dedicated /races page with paginated finished races
- Anonymous access to training session pages

### In-game

- Real-time overlay with zone name, IGT, deaths, tier, and leaderboard
- EMEVD event flag system for zone/boss detection
- Zone query for fast travel detection via warp hook
- Event flags deferred to loading screen exit for reliability
- Seed pack mismatch detection after re-roll
- File logging for debugging

### Metro map

- Metro-style DAG visualization of the seed graph
- Node popup: click any node to see fog gate text, exits/entrances, visitors, time spent, and zone deaths
- Player filtering: click leaderboard players to highlight their path on the DAG
- Progression polyline showing the current player's route
- Animated hero DAG on homepage

### Website

- Race detail with lobby, running, and finished state layouts
- Podium for finished races
- Player colors on leaderboard (20-color palette)
- OBS Overlays button for race participants
- Help & Game Rules page

### Server

- WebSocket for live race updates (mod and spectator connections)
- WebSocket scalability: parallel broadcasts, heartbeat, per-message sessions
- Discord webhook notifications on race creation and finish
- Grace mapping service for zone resolution
- Enriched zone_query with map_id fallback for death/respawn detection

### Security

- HTTPS with CSP/HSTS headers and rate limiting
- Ephemeral auth code exchange (token no longer in redirect URL)
- Optimistic locking with version column
- WebSocket authentication timeout and failure logging

### Translations

- French translation of zone names and game data
- Server-side i18n with locale support
