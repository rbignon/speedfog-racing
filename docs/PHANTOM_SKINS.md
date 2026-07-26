# Phantom Skins (Mod Side)

How the racing mod applies cosmetic phantom auras (a colored outline around the player's silhouette) at runtime, by calling Elden Ring's internal ChrIns-level SpEffect apply wrapper.

For the build-time side (regulation.bin injection, catalog file, ID range), see [`speedfog/docs/phantom-skins.md`](../../speedfog/docs/phantom-skins.md). This doc only covers what happens once the seed is loaded and the player joins a race.

## Overview

```
auth_ok message                    apply_speffect()
{                                  ┌─────────────────────────────────┐
  phantom_skin: "gold-aura",       │ AOB scan eldenring.exe (once)   │
  seed: {                          │ ↓                               │
    phantom_skins: {               │ Read PlayerIns from WorldChrMan │
      "gold-aura":                 │ ↓                               │
        { speffects: [1450700] }   │ Guard: SpEffectCtrl (PlayerIns  │
    }                              │   + 0x178) non-null             │
  }                                │ ↓                               │
}                                  │ Call wrapper(PlayerIns, id, 1)  │
        │                          └─────────────────────────────────┘
        ▼                                       ▲
  resolve name → ids ─── spawn runner ─── on every "not loaded → loaded"
                       (poll 2 Hz)        transition, re-apply each id
```

The build-time pipeline guarantees `regulation.bin` contains the SpEffect rows. The mod's job is to:

1. Receive the equipped skin name in `auth_ok.phantom_skin`.
2. Resolve it to one or more SpEffect IDs via `auth_ok.seed.phantom_skins[name].speffects`.
3. Call the game's `ApplySpEffect` function on the player every time the game world (re)loads.

## Server Contract

Two pieces arrive in `auth_ok` (see `core/protocol.rs`):

| Field                                | Type                           | Meaning                                          |
| ------------------------------------ | ------------------------------ | ------------------------------------------------ |
| `phantom_skin`                       | `Option<String>`               | Equipped skin name for this user (or `null`).    |
| `seed.phantom_skins`                 | `HashMap<String, PhantomSkin>` | Per-seed mapping `name → directives`.            |
| `seed.phantom_skins[name].speffects` | `Vec<i32>`                     | SpEffect IDs to apply. Empty = nothing to apply. |

The split is intentional: the user's chosen skin is per-session, the catalog is per-seed. An older seed without the skin in its catalog disables the feature for that race (logged warn, no error). New keys (e.g. `fxr_ids`) added later default to empty so old mods stay forward-compatible.

## Function Resolution: AOB Pattern Scan

Elden Ring does not expose the apply wrapper as a stable export, and `libeldenring`'s pointer table doesn't include it. The mod locates it by scanning the executable section of `eldenring.exe` for a 19-byte pattern matching a unique instruction sequence inside the wrapper body; the entry point is the match address minus `0x1D`.

### Pattern Source

The AOB comes from The Grand Archives Cheat Engine table (`ER_TGA_v1.17.0.CT`, script `SpEffect_code`, function `SpEffect.addForSelf`), including the `- 0x1D` entry offset. The constant lives in `eldenring/sp_effect_apply.rs::APPLY_SP_EFFECT_PATTERN` as `&[Option<u8>]`, where `Some(byte)` is an exact match and `None` is a wildcard (the `0x??` bytes in the CE script).

An earlier version of the mod used the lower-level `ChrIns_ApplySpEffect` from the Hexinton table (`ApplyEffectAOBFecth`) instead; see the next section for why that was replaced.

### Scan Flow

1. `GetModuleHandleW(None)` returns the handle of the main executable that loaded the DLL (i.e., `eldenring.exe`).
2. `GetModuleInformation` yields `(base, size_of_image)`.
3. A linear sweep over `base..base + size` looks for a matching window; the match must be unique (a pattern that matches twice resolves to an address we would execute, so ambiguity is treated as "not found").
4. The resolved address is cached in a `OnceLock<Option<usize>>`. On scan failure the `None` is also cached, so subsequent calls don't re-scan a process where the pattern shifted (e.g. a future game patch).

If the AOB ever shifts, `apply_speffect` returns `false` with a warn log and the runner becomes a no-op, but the rest of the mod keeps working.

## Calling Convention

The wrapper is invoked with the Microsoft x64 calling convention, registers only:

| Register | Argument                                                            |
| -------- | ------------------------------------------------------------------- |
| RCX      | `ChrIns*` (character receiving the effect)                          |
| EDX      | `effect_id` (u32)                                                   |
| R8D      | flag (u32, consumed as `r8b`); TGA's `addForSelf` always passes `1` |

The Rust signature is declared as `extern "system" fn(*mut c_void, u32, u32)`.

### Why the register-only wrapper

The lower-level `ChrIns_ApplySpEffect` takes seven arguments: beyond the five documented ones (SpEffectCtrl, id, emitter, target, multiplier), its prologue reads a byte at caller-`[rsp+0x30]` (7th argument) and forwards it to an inner call whose boolean result gates the application. Binding it with a 5-argument foreign signature leaves that stack slot uninitialized, so the game reads whatever local the compiler happened to place there. This worked by accident until a rustc upgrade (1.96 to 1.97) moved the `apply_speffect` frame layout by 8 bytes, silently flipping the leaked byte: the mod logged `Applied` but the aura never appeared. The Hexinton CE stub has the same latent flaw (`sub rsp,38`, five arguments) and only works by luck from CE's own thread. The register-only wrapper closes that failure class: every argument is explicit, nothing is read from the caller's stack.

## Reading PlayerIns

`PlayerIns` is reached through `WorldChrMan + offset`, where the offset depends on the game version:

| Versions               | PlayerIns offset (in `WorldChrMan`) |
| ---------------------- | ----------------------------------- |
| `V1_02_0` .. `V1_06_0` | `0x18468`                           |
| `V1_07_0` and later    | `0x1E508`                           |

`SpEffectCtrl` at `PlayerIns + 0x178` is only read as a readiness guard (the wrapper resolves it internally): if the player struct is mid-initialization (PlayerIns null, or SpEffectCtrl null), `apply_speffect` logs and returns `false`, the runner will retry on the next "loaded" transition. All offsets are constants in `sp_effect_apply.rs`.

## Background Runner

`sp_effect_runner::spawn(skin_name, speffect_ids, stop)` spawns a thread that polls `WorldChrMan + offset` every 500 ms and re-applies every SpEffect on the rising edge `not loaded → loaded`. This single loop covers:

- Initial game world load.
- `Save & Quit + Reload` (the SpEffect template `13177` may not persist).
- Grace warps that round-trip through a loading screen.

Application is idempotent at the game level: applying a SpEffect that's already active is a no-op. So missed transitions are safe, the cost is a couple of redundant calls per second at worst.

The thread reads from `OnceLock`-cached state and never blocks the per-frame paths (`RaceTracker::update`, `ImguiRenderLoop::render`).

### Lifecycle

The runner is spawned from `RaceTracker::handle_ws_message` when an `auth_ok` arrives carrying a non-null `phantom_skin`:

```text
auth_ok arrives
  │
  ├── phantom_skin == None        → no-op
  ├── runner already up for name  → log + skip respawn (reconnect path)
  ├── name not in seed catalog    → warn, feature off (older seed)
  ├── name found, speffects empty → warn (catalog has skin but no effects)
  └── name found, speffects non-empty → spawn runner
```

The `Arc<AtomicBool>` stop flag is in place for future mid-session skin changes, but currently no caller flips it: the thread dies with the process. Reconnects with the same equipped skin are cheap (the `already_running` check skips respawning the thread).

## Logging

All log lines from the apply path are tagged with `[PHANTOM_SKIN]` so they can be grepped out of the user's mod log. A successful apply prints once per transition:

```text
INFO [PHANTOM_SKIN] Runner started skin=gold-aura count=1 ids=[1450700]
INFO [PHANTOM_SKIN] Applied skin=gold-aura id=1450700
```

## Failure Modes

| Symptom                                                        | Cause                                                                             | Recovery                               |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------- |
| `ApplySpEffect AOB pattern not found (or ambiguous)`           | Game patch changed the wrapper's code, or the pattern now matches more than once. | Update `APPLY_SP_EFFECT_PATTERN`.      |
| `Skin not in this seed's catalog (older seed?)`                | Seed was generated before the skin was added to the catalog.                      | Regenerate seed, or pick another skin. |
| `Seed catalog has the skin but no SpEffects; nothing to apply` | Catalog entry has empty `speffects` (build-time bug).                             | Fix `data/phantom_skins.toml`.         |
| `Cannot apply SpEffect: player not loaded yet` (debug)         | Polled mid-loading screen.                                                        | Self-heals, the next tick succeeds.    |

## Testing

Unit tests in `core/aob.rs` cover the pattern matcher (wildcard match, no match, empty pattern, unique vs ambiguous match); tests in `sp_effect_apply.rs` validate the pattern length and anchor bytes. The full apply path is exercised in-game; `player_ins_offset()` panics outside a running ER process (via `libeldenring::version::get_version`), so it has no unit test.

For iterative skin tuning without rebuilding `regulation.bin`, see the Cheat Engine workflow in [`speedfog/docs/phantom-skins.md`](../../speedfog/docs/phantom-skins.md).
