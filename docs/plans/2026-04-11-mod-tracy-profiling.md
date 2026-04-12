# Mod Tracy Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in Tracy profiler instrumentation to the Rust mod so we can measure per-frame CPU cost of game-state reads, event-flag scans, and ImGui rendering, without impacting release builds distributed to players.

**Architecture:** All profiling is gated behind a Cargo feature `profile-tracy`. When the feature is on, `lib.rs` registers a `tracing-tracy` layer alongside the existing file logger. Instrumentation uses `tracing::debug_span!` for outer spans (cheap even when the feature is off, because the file logger's default `info` filter turns them into a callsite no-op). Inner hot-loop spans are wrapped in a `profile_span!` macro that is compiled out entirely when the feature is off. A single `tracy_client::frame_mark()` call in `ImguiRenderLoop::render` draws the frame boundary on Tracy's timeline.

**Tech Stack:** Rust 2021, tracing 0.1 (already a dep), tracing-subscriber 0.3 (already a dep), tracing-tracy 0.11, tracy-client 0.18, Tracy profiler v0.13.1.

---

## File Structure

- **Modify** `mod/Cargo.toml`: add `profile-tracy` feature and two optional deps.
- **Modify** `mod/src/lib.rs`: register `TracyLayer` conditionally and keep the client alive.
- **Create** `mod/src/core/profile.rs`: `profile_span!` macro and `frame_mark()` shim.
- **Modify** `mod/src/core/mod.rs`: expose the new `profile` module.
- **Modify** `mod/src/dll/ui.rs`: add root render span and `frame_mark()`.
- **Modify** `mod/src/dll/tracker.rs`: add spans in `update()`, leaderboard refresh, event flag polling, status update.
- **Modify** `mod/src/eldenring/game_state.rs`: add spans on memory read primitives.
- **Modify** `mod/src/eldenring/event_flags.rs`: add spans on `find_category_page`, `resolve_category`, `is_flag_set_cached`.
- **Modify** `mod/src/dll/websocket.rs`: add a top-level span in the WebSocket worker thread.
- **Create** `docs/MOD_PROFILING.md`: end-user documentation for capturing traces.

Existing files are the authoritative source for function locations and signatures. Line numbers in this plan reflect the state at commit `95ae90c`.

---

## Task 1: Add Cargo feature and optional dependencies

**Files:**

- Modify: `mod/Cargo.toml`

- [ ] **Step 1: Add `[features]` section and optional deps**

Open `mod/Cargo.toml`. Add a `[features]` section right under the `[lib]` section (before `[dependencies]`):

```toml
[features]
default = []
profile-tracy = ["dep:tracing-tracy", "dep:tracy-client"]
```

Add two optional dependencies inside the existing `[target.'cfg(windows)'.dependencies]` block (Tracy's hooks rely on native Windows TLS and the mod only runs on Windows anyway; keeping them Windows-only avoids Linux cross-compile friction):

```toml
# --- Profiling (optional, behind `profile-tracy` feature) ---
# `enable` is the master switch on both crates; removing it makes the profiler a no-op.
tracing-tracy = { version = "0.11", optional = true, default-features = false, features = [
    "enable",
    "system-tracing",
    "context-switch-tracing",
    "sampling",
    "code-transfer",
    "broadcast",
    "callstack-inlines",
] }
tracy-client = { version = "0.18", optional = true, default-features = false, features = [
    "enable",
    "system-tracing",
    "context-switch-tracing",
    "sampling",
    "code-transfer",
    "broadcast",
    "callstack-inlines",
] }
```

- [ ] **Step 2: Verify the default build still compiles on Linux**

Run:

```bash
cd mod && cargo check --lib
```

Expected: `Finished ... dev [unoptimized + debuginfo] target(s)` with no errors. Warnings about unused features are fine.

- [ ] **Step 3: Verify the feature build is valid at the manifest level**

Run:

```bash
cd mod && cargo check --lib --features profile-tracy 2>&1 | head -30
```

Expected on Linux: the feature itself is accepted; because the optional deps are Windows-gated, `cargo check` on Linux is a no-op for them. Any error message about an unknown feature means the `[features]` stanza is wrong; fix the syntax before moving on.

- [ ] **Step 4: Commit**

```bash
git add mod/Cargo.toml mod/Cargo.lock
git commit -m "feat(mod): add optional profile-tracy feature"
```

---

## Task 2: Create the profile helper module

**Files:**

- Create: `mod/src/core/profile.rs`
- Modify: `mod/src/core/mod.rs`

- [ ] **Step 1: Create `mod/src/core/profile.rs`**

Write the full file contents:

````rust
//! Profiling helpers for opt-in Tracy instrumentation.
//!
//! All symbols here are `pub(crate)`. When the `profile-tracy` feature is
//! disabled they are zero-cost no-ops (the macro expands to an empty block,
//! and `frame_mark()` becomes an empty function the compiler inlines away).
//!
//! When the feature is enabled, `profile_span!` expands to a `debug_span!`
//! that is guarded-entered, and `frame_mark()` forwards to Tracy.

/// Enter a profiling span scoped to the surrounding block.
///
/// Usage:
/// ```ignore
/// fn hot_path() {
///     crate::profile_span!("hot_path");
///     // ... work ...
/// }
/// ```
///
/// The guard is bound to a hidden local, so the span stays active until the
/// enclosing block ends. Use this form inside inner loops where you do not
/// want to write an explicit `let _g = ...;` line.
#[cfg(feature = "profile-tracy")]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {
        let _profile_span_guard = ::tracing::debug_span!($name).entered();
    };
    ($name:expr, $($field:tt)*) => {
        let _profile_span_guard = ::tracing::debug_span!($name, $($field)*).entered();
    };
}

#[cfg(not(feature = "profile-tracy"))]
#[macro_export]
macro_rules! profile_span {
    ($name:expr) => {};
    ($name:expr, $($field:tt)*) => {};
}

/// Mark the end of a rendered frame for Tracy's timeline.
///
/// Call this once per DX12 present (i.e. at the end of `ImguiRenderLoop::render`).
#[cfg(all(feature = "profile-tracy", target_os = "windows"))]
#[inline]
pub fn frame_mark() {
    tracy_client::Client::running()
        .expect("tracy client not started")
        .frame_mark();
}

#[cfg(not(all(feature = "profile-tracy", target_os = "windows")))]
#[inline]
pub fn frame_mark() {}
````

- [ ] **Step 2: Expose the module from `mod/src/core/mod.rs`**

Open `mod/src/core/mod.rs`. Add a `pub mod profile;` line next to the other `pub mod` declarations. The file should now read (existing lines plus the new one):

```rust
pub mod color;
pub mod constants;
pub mod flag_buffer;
pub mod format;
pub mod map_utils;
pub mod profile;
pub mod protocol;
pub mod traits;
pub mod types;

pub use format::{compute_gap, format_gap_into};
```

(Preserve any other `pub use` lines already present.)

- [ ] **Step 3: Verify both builds still compile**

Run:

```bash
cd mod && cargo check --lib && cargo check --lib --features profile-tracy
```

Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add mod/src/core/profile.rs mod/src/core/mod.rs
git commit -m "feat(mod): add profile_span macro and frame_mark shim"
```

---

## Task 3: Register the TracyLayer in `lib.rs`

**Files:**

- Modify: `mod/src/lib.rs:41-58`

- [ ] **Step 1: Update `init_logging` to add the Tracy layer conditionally**

Replace the body of `init_logging` (lines 41-58) with:

```rust
#[cfg(target_os = "windows")]
fn init_logging(hmodule: HINSTANCE) {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));

    if let Some(dll_dir) = RaceConfig::get_dll_directory(hmodule) {
        let file_appender = tracing_appender::rolling::never(&dll_dir, "speedfog_racing.log");
        let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);
        LOG_GUARD.set(guard).ok();

        let subscriber = Registry::default()
            .with(filter)
            .with(fmt::layer().with_writer(non_blocking).with_ansi(false));

        #[cfg(feature = "profile-tracy")]
        let subscriber = subscriber.with(tracing_tracy::TracyLayer::default());

        tracing::subscriber::set_global_default(subscriber).ok();
    } else {
        // Fallback: stderr only (original behavior)
        let subscriber = Registry::default()
            .with(filter)
            .with(fmt::layer().with_ansi(false));

        #[cfg(feature = "profile-tracy")]
        let subscriber = subscriber.with(tracing_tracy::TracyLayer::default());

        tracing::subscriber::set_global_default(subscriber).ok();
    }

    #[cfg(feature = "profile-tracy")]
    {
        // Force the Tracy client to start now so `frame_mark()` calls find it
        // already running on the first frame. Drop the handle: the client is
        // a process-wide singleton and stays alive for the DLL's lifetime.
        let _ = tracy_client::Client::start();
        info!("Tracy profiling client started");
    }
}
```

Note: this replaces the original fallback `fmt().with_env_filter(...).init();` line with an explicit Registry so the Tracy layer can be attached in both branches.

- [ ] **Step 2: Verify default build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 3: Verify profile build would compile on Windows**

The feature build cannot be checked on Linux because `tracing-tracy` is Windows-only per Task 1's manifest. Skip the Linux check and rely on the final Task 11 verification which runs on Windows.

- [ ] **Step 4: Commit**

```bash
git add mod/src/lib.rs
git commit -m "feat(mod): register TracyLayer when profile-tracy is enabled"
```

---

## Task 4: Instrument the frame boundary in `ui.rs`

**Files:**

- Modify: `mod/src/dll/ui.rs:71-131`

- [ ] **Step 1: Wrap `render()` with a span and emit `frame_mark()`**

Open `mod/src/dll/ui.rs`. At the top of the file, add the macro import alongside the other `use` lines:

```rust
use crate::profile_span;
```

Replace the body of the `render` method (lines 71-130) with:

```rust
    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        profile_span!("frame");

        // Per-frame update
        self.update();

        // Always build a window (hudhook crashes otherwise)
        if !self.show_ui {
            ui.window("##hidden")
                .position([-100.0, -100.0], Condition::Always)
                .size([1.0, 1.0], Condition::Always)
                .no_decoration()
                .build(|| {});
            crate::core::profile::frame_mark();
            return;
        }

        // Take pre-allocated buffers out of self so sub-methods can borrow
        // self immutably while mutating the buffers.
        let mut bufs = std::mem::take(&mut self.render_bufs);

        let c = &self.cached_colors;

        // Push style colors (auto-popped when tokens drop)
        let _bg_token = ui.push_style_color(StyleColor::WindowBg, c.bg);
        let _text_token = ui.push_style_color(StyleColor::Text, c.text);
        let _text_disabled_token = ui.push_style_color(StyleColor::TextDisabled, c.text_disabled);
        let _border_token = ui.push_style_color(StyleColor::Border, c.border);

        let [dw, _dh] = ui.io().display_size;
        let scale = self.config.overlay.font_size / 16.0;
        let max_width = 320.0 * scale;

        let flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        {
            profile_span!("imgui_window");
            ui.window("SpeedFog Race")
                .position(
                    [
                        dw - max_width - self.config.overlay.position_offset_x,
                        self.config.overlay.position_offset_y,
                    ],
                    Condition::FirstUseEver,
                )
                .flags(flags)
                .build(|| {
                    self.render_seed_mismatch_warning(ui);
                    self.render_player_status(ui, max_width, &mut bufs);
                    self.render_exits(ui, max_width);
                    if !self.config.server.training && self.show_leaderboard {
                        ui.separator();
                        self.render_leaderboard(ui, max_width, &mut bufs);
                    }
                    self.render_status_message(ui);
                    if self.show_debug {
                        ui.separator();
                        self.render_debug(ui);
                    }
                });
        }

        // Put buffers back (preserves capacity for next frame)
        self.render_bufs = bufs;

        crate::core::profile::frame_mark();
    }
```

Two spans are added: `frame` covers the whole function (including `self.update()`), and `imgui_window` covers only the ImGui window build. `frame_mark()` runs on both the early-return and the normal path.

- [ ] **Step 2: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 3: Commit**

```bash
git add mod/src/dll/ui.rs
git commit -m "feat(mod): instrument imgui render loop with Tracy spans"
```

---

## Task 5: Instrument `RaceTracker::update` and its sub-blocks

**Files:**

- Modify: `mod/src/dll/tracker.rs:427-822`

- [ ] **Step 1: Add the macro import at the top of the file**

Open `mod/src/dll/tracker.rs`. Add next to the existing `use` lines:

```rust
use crate::profile_span;
```

- [ ] **Step 2: Wrap `update()` with an outer span**

Insert `profile_span!("tracker_update");` as the very first line inside `pub fn update(&mut self)` (line 427), before the existing `begin_hotkey_frame();` call.

- [ ] **Step 3: Wrap the WebSocket poll loop**

Replace the block at line 458-461:

```rust
        // Poll WebSocket
        while let Some(msg) = self.ws_client.poll() {
            self.handle_ws_message(msg);
        }
```

with:

```rust
        {
            profile_span!("ws_poll");
            while let Some(msg) = self.ws_client.poll() {
                self.handle_ws_message(msg);
            }
        }
```

- [ ] **Step 4: Wrap the frame snapshot read**

Replace the block at line 463-477:

```rust
        let need_live_snapshot = self.show_ui || self.ws_client.is_connected();
        self.frame_snapshot = FrameSnapshot {
            igt_ms: need_live_snapshot
                .then(|| self.game_state.read_igt())
                .flatten(),
            death_count: need_live_snapshot
                .then(|| self.game_state.read_deaths())
                .flatten(),
            position_readable: self.game_state.is_position_readable(),
            loading_screen: if self.pending_zone_update.is_some() {
                self.game_state.is_in_loading_screen()
            } else {
                None
            },
        };
```

with:

```rust
        let need_live_snapshot = self.show_ui || self.ws_client.is_connected();
        self.frame_snapshot = {
            profile_span!("frame_snapshot");
            FrameSnapshot {
                igt_ms: need_live_snapshot
                    .then(|| self.game_state.read_igt())
                    .flatten(),
                death_count: need_live_snapshot
                    .then(|| self.game_state.read_deaths())
                    .flatten(),
                position_readable: self.game_state.is_position_readable(),
                loading_screen: if self.pending_zone_update.is_some() {
                    self.game_state.is_in_loading_screen()
                } else {
                    None
                },
            }
        };
```

- [ ] **Step 5: Wrap the event flag polling block**

Find the `if !self.event_ids.is_empty() && self.last_flag_poll.elapsed() >= Duration::from_millis(100)` block (starts at line 624). Insert `profile_span!("event_flag_poll");` as the first statement inside the block, immediately after the opening `{`.

- [ ] **Step 6: Wrap the loading-screen-exit rescan block**

Find the `if position_readable && !self.was_position_readable` block (starts at line 512). Insert `profile_span!("loading_exit_scan");` as the first statement inside the block.

- [ ] **Step 7: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 8: Commit**

```bash
git add mod/src/dll/tracker.rs
git commit -m "feat(mod): instrument RaceTracker::update hot blocks"
```

---

## Task 6: Instrument the leaderboard cache refresh

**Files:**

- Modify: `mod/src/dll/ui.rs:476-637`

- [ ] **Step 1: Wrap `render_leaderboard` and `refresh_leaderboard_cache`**

In `mod/src/dll/ui.rs`, insert `profile_span!("render_leaderboard");` as the first line of `fn render_leaderboard` (line 476-481 signature, first line of body at 482).

Insert `profile_span!("refresh_leaderboard_cache");` as the first line of `fn refresh_leaderboard_cache` (line 533 signature, first line of body at 534).

- [ ] **Step 2: Wrap the per-row `calc_text_size` loop**

Find the `for (i, p) in participants.iter().enumerate()` loop (line 579). Insert `profile_span!("leaderboard_rows");` on the line immediately before the `for` keyword, inside the enclosing block so the span covers the whole loop plus its post-processing up to line 617.

Concretely, the code:

```rust
        let cache = &mut self.leaderboard_cache;
        cache.rows.clear();
        cache.max_gap_width = 0.0;
        cache.max_right_width = 0.0;

        for (i, p) in participants.iter().enumerate() {
```

becomes:

```rust
        let cache = &mut self.leaderboard_cache;
        cache.rows.clear();
        cache.max_gap_width = 0.0;
        cache.max_right_width = 0.0;

        profile_span!("leaderboard_rows");
        for (i, p) in participants.iter().enumerate() {
```

The span is scoped to the enclosing function body, so it stays active until the function returns. That is the desired behavior: we want to measure everything that happens after this point in `refresh_leaderboard_cache`.

- [ ] **Step 3: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 4: Commit**

```bash
git add mod/src/dll/ui.rs
git commit -m "feat(mod): instrument leaderboard cache refresh"
```

---

## Task 7: Instrument game state memory reads

**Files:**

- Modify: `mod/src/eldenring/game_state.rs:67-147`

- [ ] **Step 1: Import the macro**

At the top of `mod/src/eldenring/game_state.rs`, add:

```rust
use crate::profile_span;
```

- [ ] **Step 2: Wrap each read primitive**

Add a `profile_span!` call as the first line inside each of the following method bodies. Four of them are inherent `impl GameState` methods; `read_position` is defined on the `GameStateReader` trait impl.

- `pub fn read_deaths` (inherent impl, body at line 71): `profile_span!("read_deaths");`
- `pub fn read_igt` (inherent impl, body at line 78): `profile_span!("read_igt");`
- `pub fn is_in_loading_screen` (inherent impl, body at line 87): `profile_span!("is_in_loading_screen");`
- `pub fn is_position_readable` (inherent impl, body at line 94): `profile_span!("is_position_readable");`
- `fn read_position` (trait impl, body at line 126): `profile_span!("read_position");`

- [ ] **Step 3: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 4: Commit**

```bash
git add mod/src/eldenring/game_state.rs
git commit -m "feat(mod): instrument GameState memory reads"
```

---

## Task 8: Instrument event flag reader

**Files:**

- Modify: `mod/src/eldenring/event_flags.rs:103-400`

- [ ] **Step 1: Import the macro**

At the top of `mod/src/eldenring/event_flags.rs`, add:

```rust
use crate::profile_span;
```

- [ ] **Step 2: Add spans on the five hot functions**

Insert `profile_span!("event_flag.is_flag_set");` as the first line of `pub fn is_flag_set` body (line 153+).

Insert `profile_span!("event_flag.set_flag");` as the first line of `pub fn set_flag` body (line 103+).

Insert `profile_span!("event_flag.resolve_category");` as the first line of `pub fn resolve_category` body (line 185+).

Insert `profile_span!("event_flag.is_flag_set_cached");` as the first line of `pub fn is_flag_set_cached` body (line 253+).

Insert `profile_span!("event_flag.find_category_page");` as the first line of `fn find_category_page` body (line 333+).

This is the most important one of the five: `find_category_page` walks the game's red-black tree in memory and is the suspected hotspot.

- [ ] **Step 3: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 4: Commit**

```bash
git add mod/src/eldenring/event_flags.rs
git commit -m "feat(mod): instrument EventFlagReader hot paths"
```

---

## Task 9: Instrument the WebSocket worker thread

**Files:**

- Modify: `mod/src/dll/websocket.rs:292-400`

- [ ] **Step 1: Import the macro**

At the top of `mod/src/dll/websocket.rs`, add:

```rust
use crate::profile_span;
```

- [ ] **Step 2: Name the worker thread and add a thread-scoped span**

Find the `fn websocket_thread` (line 292). Insert as the first line of its body:

```rust
    tracy_client::set_thread_name!("ws-worker");
    profile_span!("ws_thread");
```

The `set_thread_name!` call is only defined when `tracy-client` is in the dep graph. Wrap it in a cfg block so the default build still compiles:

```rust
    #[cfg(feature = "profile-tracy")]
    tracy_client::set_thread_name!("ws-worker");
    profile_span!("ws_thread");
```

- [ ] **Step 3: Verify the build**

Run:

```bash
cd mod && cargo check --lib
```

Expected: success.

- [ ] **Step 4: Commit**

```bash
git add mod/src/dll/websocket.rs
git commit -m "feat(mod): name and instrument websocket worker thread"
```

---

## Task 10: Write end-user profiling documentation

**Files:**

- Create: `docs/MOD_PROFILING.md`

- [ ] **Step 1: Create the doc file**

Write the full contents of `docs/MOD_PROFILING.md`:

````markdown
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

1. **Tracy server 0.11.** Download from https://github.com/wolfpld/tracy/releases
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
````

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

````

- [ ] **Step 2: Commit**

```bash
git add docs/MOD_PROFILING.md
git commit -m "docs: add mod Tracy profiling guide"
````

---

## Task 11: Final verification and code review

**Files:** All modified files above.

- [ ] **Step 1: Clean build at default settings**

Run:

```bash
cd mod && cargo clean && cargo check --lib && cargo build --lib
```

Expected: both succeed with no warnings introduced by this plan. Pre-existing warnings are OK.

- [ ] **Step 2: Windows-only: feature build**

On a Windows MSVC machine (or if `cargo check --lib --features profile-tracy --target x86_64-pc-windows-msvc` is available):

```bash
cd mod && cargo build --lib --release --features profile-tracy
```

Expected: produces `target/release/speedfog_racing.dll`. On Linux this step is skipped because the Tracy deps are Windows-gated.

- [ ] **Step 3: Run the code review agent**

Per the project rule "Launch a code review agent before the final commit of a task", invoke the `superpowers:code-reviewer` agent to review all commits made on this branch since the plan started. Fix anything it flags, re-commit, and re-run the agent if major changes were required.

- [ ] **Step 4: Smoke test in game (Windows only)**

1. Copy the profiling DLL into your Elden Ring mod folder.
2. Launch Tracy server UI, click Connect.
3. Inject the mod.
4. Confirm that:
   - `speedfog_racing.log` contains `Tracy profiling client started`.
   - Tracy UI shows a `frame` zone firing every frame.
   - At least one `tracker_update` zone and one `event_flag_poll` zone are visible.
5. Eject the mod.

- [ ] **Step 5: Final commit (if code review required fixes)**

```bash
git status
git commit -am "fix(mod): address code review feedback on Tracy instrumentation"
```

If the review passed without changes, skip this step; there is nothing to commit.

---

## Open questions / assumptions

- The `tracing-tracy` and `tracy-client` crate versions (`0.11` and `0.18`) are
  assumed current as of 2026-04. The `tracy-client` version was bumped from 0.17
  to 0.18 during implementation review to match what `tracing-tracy 0.11`
  internally depends on, eliminating a duplicate in the lockfile. If `cargo
check` complains about API drift, bump to the latest compatible pair and
  adjust the two call sites (`TracyLayer::default()` and
  `Client::running().frame_mark()`).
- Tracy's TCP port (8086) is assumed reachable from the Tracy UI to the game
  process. If a firewall blocks it, either allow the port or use Tracy's
  on-demand capture mode (server-initiated connection still uses the same
  port).
- This plan does not instrument the `hotkey` module or `death_icon` texture
  load. Those are cold paths and not worth the noise.
