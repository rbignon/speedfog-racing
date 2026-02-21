# Changelog

All notable changes to SpeedFog Racing are documented in this file.

## [Unreleased]

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
