# Profiling the SpeedFog Racing Mod with Tracy

This guide explains how to capture a performance trace of the Rust mod while
it runs inside Elden Ring. Profiling is **opt-in**: the default build ships
with zero profiling code, so normal players are not affected.

## What you get

When profiling is enabled, the mod sends a live trace to the Tracy profiler
UI over TCP port `8086`. You can see:

- Per-frame CPU cost of ImGui rendering (`frame` and `imgui_window` spans).
- Per-frame cost of `RaceTracker::update` and its sub-blocks (`tracker_update`,
  `ws_poll`, `frame_snapshot`, `event_flag_poll`, `loading_exit_scan`).
- Leaderboard rebuild cost (`render_leaderboard`, `refresh_leaderboard_cache`,
  `leaderboard_rows`).
- Game memory reads (`read_igt`, `read_deaths`, `read_position`,
  `is_position_readable`, `is_in_loading_screen`).
- Event flag reader hot paths (`event_flag.find_category_page`,
  `event_flag.resolve_category`, `event_flag.is_flag_set_cached`, etc.).
- A separate timeline for the WebSocket worker thread (`ws-worker`).

## Prerequisites

1. **Tracy server 0.11.** Download from <https://github.com/wolfpld/tracy/releases>
   or build from source. The major version of the server **must match** the
   major version of the `tracy-client` crate used by the mod, otherwise the
   client will refuse to connect.
2. **Windows MSVC toolchain** for building the mod (same as normal dev).
3. **Elden Ring launched offline** (already required for `hudhook` injection).

## Build the profiling DLL

From the repository root, on Windows:

```bat
cd mod
cargo build --lib --release --features profile-tracy
```

The resulting `target\release\speedfog_racing.dll` is **only for profiling**.
Do not distribute it to players: it keeps the Tracy client linked in and
opens a TCP listener.

## Capture a trace

1. Start the Tracy server UI (`Tracy.exe`). Click **Connect** and leave the
   address at `127.0.0.1`.
2. Inject the profiling DLL into Elden Ring the same way you normally inject
   the mod (hudhook injector or your usual launcher). You should see a log
   line in `speedfog_racing.log` that reads `Tracy profiling client started`.
3. The Tracy UI should pick up the connection within a second. You will see
   frames streaming in live.
4. Play normally. Spans are grouped by name; hover any zone to see its
   duration. Right-click a zone name in the left panel to plot its history
   across frames.
5. When you are done, stop capture in Tracy (**File > Save trace...**) to keep
   the result for later analysis, then eject the mod.

## What to look at first

- **`frame` duration.** At 60 FPS the budget is 16.6 ms. Anything the mod adds
  to this is directly visible.
- **`find_category_page` under `event_flag_poll`.** This walks the game's
  red-black tree every 100 ms. If you see it spiking above a few microseconds
  per call, the cache is being invalidated too often.
- **`refresh_leaderboard_cache` frequency.** It is throttled to 250 ms via the
  IGT bucket. Seeing it fire on every frame means the throttle is broken.
- **`imgui_window` vs `tracker_update` ratio.** If rendering dominates, investigate
  `render_leaderboard`. If logic dominates, investigate the event flag loop.

## Notes and caveats

- The profiling build **disables** the `strip = "symbols"` setting effectively,
  because `tracy-client` needs function names. Release profile tweaks still
  apply, so optimizations are on.
- Tracy opens a TCP listener on `0.0.0.0:8086`. Do not run a profiling build on
  a machine exposed to an untrusted network.
- EAC is bypassed by launching the game offline; profiling does not require
  any additional anti-cheat workaround.
- The `profile_span!` macro is defined in `mod/src/core/profile.rs`. Add new
  spans there in the same style as existing ones.

## Adding a new span

```rust
use crate::profile_span;

fn my_hot_function() {
    profile_span!("my_hot_function");
    // ... work ...
}
```

Rebuild with `--features profile-tracy` and reconnect Tracy. The new zone
appears automatically.

## Disabling profiling

Build the mod without the feature (the default). All profiling code is
compiled out; `speedfog_racing.log` will no longer show `Tracy profiling
client started`.
