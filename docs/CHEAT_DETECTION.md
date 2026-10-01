# Cheat detection

The race mod notices the game's own debug flags, the switches the practice
tool and TarnishedTool toggle ("One shot", "No death", infinite stamina...),
warns the runner and reports the detection to the race organizer and the
admins. It targets the easy, opportunistic cheat; anything client-side can
be bypassed by a determined cheater (patching the DLL, scripting the mod
WebSocket), which is out of scope.

## What is watched

Elden Ring keeps its debug-menu switches in a static byte array
(libeldenring's `chr_dbg_flags`): one byte per switch, non-zero = on, never
saved, reset by a game restart. The retail game never sets them.

| Offset | Wire name              | Tool option                      |
| ------ | ---------------------- | -------------------------------- |
| +0x1   | `player_no_death`      | No death (both tools)            |
| +0x2   | `torrent_no_death`     | Torrent no death (practice tool) |
| +0x3   | `one_shot`             | One shot (both tools)            |
| +0x4   | `infinite_consumables` | Infinite consumables             |
| +0x5   | `infinite_stamina`     | Infinite stamina                 |
| +0x6   | `infinite_fp`          | Infinite FP                      |
| +0x7   | `infinite_arrows`      | Infinite arrows                  |
| +0x9   | `hidden`               | Hidden (TarnishedTool)           |
| +0xA   | `silent`               | Silent (TarnishedTool)           |
| +0xB   | `all_no_death`         | No death, all characters         |
| +0xC   | `all_no_damage`        | No damage, all characters        |
| +0xD   | `all_no_hit`           | No hit, all characters           |
| +0xE   | `all_no_attack`        | Characters do not attack         |
| +0xF   | `all_no_move`          | Characters do not move           |
| +0x10  | `all_no_ai`            | AI disabled                      |
| +0x12  | `infinite_aow_fp`      | Infinite FP for Ashes of War     |

The table lives in `mod/src/core/debug_flags.rs`; the server
(`DEBUG_FLAG_LABELS` in `server/speedfog_racing/services/debug_flags.py`, used
by the Discord alert) and the web (`web/src/lib/debugFlags.ts`) mirror the
wire names and carry the same human-readable labels.

## Flow

1. **Mod.** While racing (not in training, after the countdown, before the
   local finish or abandon, on a save the server accepts), the mod reads the
   19 bytes at most every 100 ms (one `ReadProcessMemory` call). When the
   server rejects the save (fresh save required, wrong save), the flags seen
   so far are dropped: they belong to a save that is not the race run. It keeps the flags seen since the
   race start and sends their names in every `status_update`
   (`debug_flags`, protocol 1.5). While a flag is on, the overlay shows a red
   "CHEAT TOOL DETECTED / Reported to the race organizer" banner; it never
   names the flag. Nothing is read or shown before the start, so the banner
   cannot be used to probe which options are watched.
2. **Server.** On an accepted `status_update`, each flag not yet stored is
   added to `participants.debug_flags` with its IGT, zone and server time
   (first observation wins). Race resets and rerolls keep it.
3. **Alerts.** New flags push `debug_flags_detected` to the race's organizer
   and admins over the spectator WebSocket and post to the private admin
   Discord channel (`DISCORD_ADMIN_WEBHOOK_URL`).
4. **Web.** The race page shows a "Flagged" chip in the leaderboard and a
   "Cheat detections" panel, to the organizer and admins only. /admin lists
   every detection in the Races tab (`GET /api/admin/cheat-detections`).

There is no automatic sanction: the race staff decide (see Sanctions).

## Sanctions

Two manual tools, for a detection or for anything else the staff find (an
audit after the race, a report).

**Disqualification** (one runner, one race). The race organizer or an admin
(on a daily, whose organizer is the system account, admins only) picks
"Disqualify a runner..." in the race controls, or "Disqualify" next to a
runner in the "Cheat detections" panel, which suggests a reason naming what
was detected. A reason is required. It works while the race runs and after
it finishes, and the same people can cancel it from the same dialog.

- The runner gets the terminal `disqualified` status (see
  `RACE_LIFECYCLE.md`) and stays at the bottom of the standings with a
  public "DQ" tag. The reason is shown to the runner (race page, and a
  "DISQUALIFIED" notice in the overlay of a runner still in game), the
  organizer and admins only.
- A disqualified run has no time, placement, points or rewards and is left
  out of the stats. Daily points and the event qualifier ladder leave the
  runner out, so the others score as if they had not run; an event playoff
  race counts them as a DNF on 0 points that never wins a tie-break.
- In a running race, the remaining runners may now all be done, which
  finishes the race. In a finished race, the race win and daily rewards are
  granted again from the new standings, so the new winner gets them, and the
  race traits are recomputed. Rewards the disqualified runner already got
  are not taken back automatically: admins revoke them by hand.
- A race reset or a daily reroll keeps the disqualification. Cancelling it
  restores the previous status and the run, or, if the race restarted in the
  meantime, lets the runner start over like everyone else.
- A disqualified or flagged participation cannot be left or removed, so the
  record stays for review.

**Ban** (one account). An admin bans from the /admin Users tab ("Ban...",
with a reason shown to the user) and lifts it with "Unban". Admins cannot be
banned. The ban is an attribute of the account (`banned_at`, `ban_reason`):
the role and past results stay as they are, and nothing public shows it.

- It blocks creating, joining and casting races, accepting invitations,
  being added to a race, training, event signups, chat messages and
  reactions, and mod connections (race and training). Signing in, browsing,
  the profile, settings and feedback stay open, and a banner tells the user
  why the rest refuses them.
- At ban time: entries in races not started yet are removed, unless under
  review (a detection or a disqualification); entries in running races are
  disqualified with the reason "Account banned" and their mod connection is
  closed; pending invitations and signups to events still open are removed;
  active training sessions end as if abandoned by hand.
- Lifting the ban restores the access only: removed entries and
  disqualifications stay (a disqualification is cancelled from its race
  page).

Every disqualification, cancellation, ban and unban is posted to the admin
Discord channel.

## Not detected

- **Per-character bits.** `CSChrDataModule + 0x19B` (bit 0 no death, bit 1
  no damage) and `ChrInsFlags` bit 3 (no hit), used by TarnishedTool's player
  "No Damage" and Torrent "No death". Retail event scripts make the player
  immortal or invincible in some sequences (`SetCharacterImmortality(10000,
...)` at the Chapel of Anticipation, in boss warps, and in one
  FogMod-added event), and whether they write these bits is unknown. They
  are added only after an in-game test logs them through those sequences
  and shows no script sets them.
- **Code hooks and direct writes:** TarnishedTool's "Lock HP" and infinite
  poise (code caves), HP edits in the practice tool's stats editor.
- **The practice tool's grace warp** (same warp function as a map fast
  travel).

## Live checklist (Windows)

1. Run a full normal race. `speedfog_racing.log` shows `[RACE] Debug flags:
0x0` at the start and never another value. Make sure the run goes
   through the Chapel of Anticipation start, at least one boss warp, and
   casts Unseen Form and Assassin's Approach (retail stealth effects, next
   to the watched `hidden` and `silent` bytes).
2. In a test race, toggle each watched option in the practice tool, then in
   TarnishedTool. Each one shows the banner within a fraction of a second,
   the "Flagged" chip and the panel on the organizer's race page, a Discord
   message in the admin channel and a row in /admin. Switching the option
   off removes the banner; the detection stays.
3. Toggle an option during the countdown and before the start: no banner;
   still on after the countdown: banner and detection at the start IGT.
4. In a deathless race, die (the server abandons you), then toggle an
   option: no banner, no detection.
5. In a Tracy capture (`docs/MOD_PROFILING.md`), `read_debug_flags` costs a
   few microseconds and runs about 10 times per second.
