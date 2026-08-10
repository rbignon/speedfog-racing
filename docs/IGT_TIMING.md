# IGT Normalization

How the mod corrects Elden Ring's in-game timer (IGT) for framerate-dependent truncation loss and blackscreen-fade bias, so IGT-ranked races stay comparable across machines with different hardware.

## Why

Elden Ring increments its in-game timer once per frame by `frame_delta_secs * 1000.0 * 0.96` (`IGT_SCALE` in `core/igt_fix.rs`; the game deliberately runs IGT at 96% of real time), then truncates the result to a whole millisecond before adding it to the timer.

At a locked 60 FPS this is exact: `1/60 * 1000 * 0.96 = 16.0` on the nose, nothing is discarded. At any other framerate the fractional remainder is silently dropped every frame. At 58 FPS, for example, `1/58 * 1000 * 0.96 ≈ 16.55`, truncated to `16`, losing about 3% of the true elapsed IGT every frame. A machine that cannot hold a locked 60 FPS therefore accumulates a _slower_ (favorably shorter) timer than a machine that can, an advantage in IGT-ranked races that has nothing to do with in-game skill.

A second, independent bias: IGT keeps ticking during blackscreen loading fades (death, fast travel, fog gate loads), and fade length is hardware-dependent (SSD vs HDD, GPU driver, etc.). Two players who took the exact same in-game actions can finish with different IGT purely because one machine's disk is faster.

Both biases are corrected mod-side, before any value reaches the wire: the truncation fix (below) makes the increment itself framerate-independent, and the blackscreen freeze holds the timer still while a fade covers the screen.

## Truncation Fix

`core/igt_fix.rs` implements `IgtFix`, a fractional-millisecond accumulator: each call to `corrected_delta_ms(frame_delta_secs)` recomputes `frame_delta_secs * 1000.0 * IGT_SCALE`, floors it, and banks the discarded fraction in `buffer`. Once `buffer` exceeds `1.0` it subtracts `1.0` and adds one whole millisecond to the returned delta. This makes the corrected increment framerate-independent while keeping the official 0.96 scale: at locked 60 FPS the buffer never accumulates anything extra (the product is already a whole number), and at any other framerate the corrected total tracks `0.96 * real_time` instead of drifting.

The arithmetic is pure and Linux-testable; the unsafe part that feeds it, `eldenring/igt_hook.rs`, is Windows-only. It installs an [ilhook](https://docs.rs/ilhook) `JmpBack` hook via `Hooker::new`, ported from SoulSplitter's `soulmods` (see Attribution). The hook target is found by scanning the live `eldenring.exe` image for `INCREMENT_IGT_PATTERN`, SoulSplitter's "increment IGT" byte pattern ending exactly on the `mulss` instruction that scales the raw frame delta (`frame_delta_secs * IGT_SCALE`). The hook address is `match_addr + INCREMENT_IGT_PATTERN.len()`, i.e. right after that `mulss`: at that point xmm0 still holds the raw delta in seconds and xmm1 holds the value the game is about to truncate. The `JmpBack` callback (`increment_igt`) reads xmm0, runs it through `IgtFix::corrected_delta_ms`, and overwrites xmm1 with the whole-millisecond result, so the game's own truncating cast loses nothing.

`install()` is called once from `RaceTracker::new`, off a spawned background thread (alongside the quit-out AOB warm-up), because the scan walks the entire module image. The hook is installed for the whole process lifetime: on success the `HookPoint` is deliberately leaked (`std::mem::forget`) rather than dropped, since dropping it would unpatch the site while the game could be executing it, mirroring the never-uninstalled warp detour. The accumulator itself lives in a `static IGT_FIX: Mutex<IgtFix>`, shared with nothing but the hook callback, so contention is not a concern at one lock per frame.

Failure policy is warn-and-continue: if the pattern scan or the hook install fails, the fix is simply disabled and racing proceeds on vanilla (lossy) IGT. A game patch or a missing hook affects every participant of a seed identically, so it degrades fairness uniformly rather than blocking racing. See Degradation Modes below for the exact log lines.

## Blackscreen Freeze

`GameState` (`eldenring/game_state.rs`) exposes two CSMenuManImp-derived signals, both ported from SoulSplitter:

- **Screen state** (`is_screen_in_game`): reads `CSMenuManImp + <offset>` as an `i32` and compares it against `SCREEN_STATE_IN_GAME = 0` (SoulSplitter's `ScreenState`: `0` = InGame, `1` = Loading, `256` = MainMenu). The offset is version-mapped in `screen_state_offset`: `0x730` for the exe 2.2+ / app 1.12+ build group (`V2_02_0` through `V2_06_2`), `None` for pre-DLC builds and any other version not in that list (the platform does not race on unmapped builds; an unmapped offset only degrades the signals below, it never blocks racing).
- **Blackscreen fade** (`is_blackscreen_active`): first requires `is_screen_in_game() == Some(true)` (fading only makes sense while already in-game), then reads the fade flag word at `CSMenuManImp + 0x18` (`MENUMAN_BLACKSCREEN_FLAGS_OFFSET`) and checks `bit0 == 1 && bit8 == 0 && bit16 == 1`, SoulSplitter's `IsBlackscreenActive` condition. Returns `Some(false)` when simply not fading (or not in game), `None` when the screen-state signal itself is unavailable.

### RaceMachine Gate

`RaceMachine::freeze_gate_open(now)` mirrors the quit-out penalty gate: the freeze may only fire while the race is running, the local player has not finished, no countdown is active, and `wrong_save` is not set (never write the timer of a save that is not the race save). `pre_tick` reads the blackscreen chains whenever this gate is open (or a zone reveal is pending, since the same signals feed that path too, see Zone Reveal below).

### The Freeze Block

At the top of `RaceMachine::tick`, before anything else, the freeze block runs (ported from SoulSplitter's `UpdateTimer`):

```
raw_igt = frame_snapshot.igt_ms, filtered to > 0
freezing = freeze_gate_open(now)
        && frame_snapshot.blackscreen == Some(true)
        && raw_igt and freeze_last_igt both present
        && raw_igt > freeze_last_igt
        && raw_igt < freeze_last_igt + BLACKSCREEN_FREEZE_MAX_STEP_MS   // 1_000 ms

if freezing:
    push Effect::FreezeIgt { ms: freeze_last_igt }
    frame_snapshot.igt_ms = Some(freeze_last_igt)   // overwrite for the rest of this tick
elif raw_igt present:
    freeze_last_igt = raw_igt                        // baseline tracks real IGT while not fading
```

`freeze_last_igt` is the baseline: "last IGT seen outside a freezable fade" (SoulSplitter's `_inGameTime`). While a fade is active and the game's own IGT creep since the baseline stays under `BLACKSCREEN_FREEZE_MAX_STEP_MS = 1_000` ms, the mod treats it as in-fade ticking and re-emits `Effect::FreezeIgt` every frame to hold the displayed/reported timer at the baseline. A jump of `1_000` ms or more is treated as a real discontinuity (a save load happening to land during a fade) rather than fade creep, so the block falls through to the `elif` branch and re-seeds the baseline from the new value instead of freezing at a stale one.

**Ordering matters**: this block runs _before_ the reload/quit-out regression detector further down `tick`, and it overwrites `frame_snapshot.igt_ms` with the frozen value when freezing. Without that override, the detector would see the write-back's own side effect: each frame the game engine ticks IGT up a little from the value the _previous_ frame's `Effect::FreezeIgt` just wrote back, producing a sawtooth in the raw reads that would otherwise look like tiny regressions and could arm a false quit-out.

**Write-back**: `Effect::FreezeIgt { ms }` is executed by the shell (`dll/tracker.rs`'s effect loop) as `game_state.write_igt(ms)`, the same 4-byte `GameDataMan + 0xA0` chain (`igt_write_ptr`) used for quit-out penalty writes. A write failure (chain transiently unwritable) is logged at `debug!` rather than `warn!`, deliberately: it can fire every frame of a fade, and a `warn!` at that rate would spam the log for the length of the loading screen.

**Baseline resets**: `freeze_last_igt` is cleared to `None` in two places, both to avoid freezing against a stale reference:

- On `RaceStart`: a fresh race begins with a clean slate, so a pre-start fade cannot leave the freeze holding a value from before the race began.
- After a quit-out penalty write (`ApplyIgtPenalty`): the penalty write invalidates whatever baseline was recorded, so the next clear (non-fading) frame re-seeds it from the penalized IGT, at most one unfrozen fade frame as the cost.

## Zone Reveal

The same CSMenuManImp screen-state/blackscreen signals described above are not exclusive to the freeze: they also drive the primary (non-loading-byte) zone reveal path, so a reveal can fire on the exact frame the destination becomes visible instead of waiting on the legacy world-clock proxy. See `docs/EVENT_FLAG_TRACKING.md`'s "Zone Reveal Timing" section for the full reveal logic and its fallback/timeout behavior; it is not duplicated here.

## Degradation Modes

Every signal this doc describes degrades gracefully: on failure the mod falls back to a less precise behavior rather than blocking racing, because a missing AOB or an unmapped game build affects every participant of a seed identically.

| Cause                                                                                                   | Log message                                                                                                          | Effect                                                                                                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Module image unqueryable (`GetModuleHandleW`/`GetModuleInformation` fails)                              | `[IGT] Failed to query eldenring.exe module info; truncation fix disabled`                                           | Truncation-fix scan never runs; vanilla lossy IGT increments for the whole process.                                                                                                                                                                      |
| Increment-IGT AOB not found: game patch shifted or changed the pattern                                  | `[IGT] increment-IGT pattern not found (game patch, or another IGT tool already hooked it); truncation fix disabled` | Same as above: truncation fix stays uninstalled.                                                                                                                                                                                                         |
| Concurrent IGT tool (e.g. SoulSplitter) already hooked the same bytes, so the pattern no longer matches | Same log line as above; the two causes are indistinguishable from the scan's point of view                           | Same as above.                                                                                                                                                                                                                                           |
| ilhook install failure (`Hooker::hook()` returns `Err`, e.g. detour write fails)                        | `[IGT] Failed to install truncation-fix hook` (with the ilhook error)                                                | Same as above.                                                                                                                                                                                                                                           |
| Unmapped game build: `screen_state_offset` has no entry for the running `Version`                       | `[IGT] No screen-state offset mapped for this game build; blackscreen freeze and direct reveal signal disabled`      | `screen_state_ptr` is `None`; `is_screen_in_game`/`is_blackscreen_active` return `None` every frame; the freeze condition never matches (falls to the `elif` branch, baseline keeps tracking real IGT); zone reveal falls back to the loading-byte path. |
| Screen-state/blackscreen pointer chain transiently unreadable (in-game but chain read fails that frame) | None (silent `Option::None` per frame; would spam at 60Hz if logged)                                                 | That frame's `frame_snapshot.blackscreen` is `None`, so `freezing` is `false` for that frame; resumes automatically once the chain is readable again.                                                                                                    |
| IGT write chain unwritable during a freeze write-back                                                   | `[IGT] Freeze write failed (IGT unwritable)` (`debug!`, not `warn!`, since it can repeat every frame of a fade)      | That frame's rewrite is skipped; the in-memory IGT may tick slightly ahead for that frame, corrected again next frame the chain is writable.                                                                                                             |

## Attribution

The truncation-fix accumulator (`core/igt_fix.rs`), its hook (`eldenring/igt_hook.rs`), and the blackscreen-freeze logic (the screen-state/blackscreen reads in `eldenring/game_state.rs`, the freeze block in `core/race_machine.rs`) are ported from [SoulSplitter](https://github.com/FrankvdStam/SoulSplitter)'s `soulmods`, licensed GPLv3. SoulSplitter's GPLv3 is compatible with this crate's own license (`AGPL-3.0`, see `mod/Cargo.toml`).

## Constants Summary

| Constant                           | Value      | Location                                       | Purpose                                                                                                  |
| ---------------------------------- | ---------- | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `IGT_SCALE`                        | `0.96`     | `core/igt_fix.rs`                              | Elden Ring's official IGT-to-real-time ratio                                                             |
| `GAMEDATAMAN_IGT_OFFSET`           | `0xA0`     | `core/constants.rs`                            | `GameDataMan` IGT field, u32 milliseconds; also used for quit-out penalty and freeze write-back          |
| `MENUMAN_BLACKSCREEN_FLAGS_OFFSET` | `0x18`     | `core/constants.rs`                            | `CSMenuManImp` fade flag word                                                                            |
| `SCREEN_STATE_IN_GAME`             | `0`        | `core/constants.rs`                            | `CSMenuManImp` screen-state value meaning "in game" (`1` = loading, `256` = main menu)                   |
| Screen-state offset                | `0x730`    | `eldenring/game_state.rs::screen_state_offset` | `CSMenuManImp` screen-state field, exe 2.2+ / app 1.12+ builds only                                      |
| `BLACKSCREEN_FREEZE_MAX_STEP_MS`   | `1_000` ms | `core/race_machine.rs`                         | Max in-fade IGT creep per frame before a jump is treated as a real discontinuity instead of fade ticking |
