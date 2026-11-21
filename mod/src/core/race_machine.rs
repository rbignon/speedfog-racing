//! Race state machine - pure, platform-independent race tracking logic.
//!
//! `RaceMachine` owns every piece of race state that is plain data and makes
//! every decision: WS message handling (`handle_message`) and the per-frame
//! flag/zone lifecycle (`tick`). It performs no IO: the Windows shell
//! (`dll/tracker.rs`) reads game memory up front (`FrameSnapshot`,
//! `TickInput`) and executes the returned `Effect`s afterwards. This is what
//! makes the state machine testable under `cargo test` on Linux.
//!
//! The blackscreen IGT-freeze logic is ported from SoulSplitter
//! (https://github.com/FrankvdStam/SoulSplitter, GPLv3; compatible with
//! this crate's AGPL-3.0).

use std::collections::HashMap;
use std::mem::{discriminant, Discriminant};
use std::time::Instant;

use crate::core::hunter::{self, Hunter, HunterNotice, HunterSpec, HunterStep};
use crate::core::item_feed::{FeedBanner, FeedHeld, FeedRow, FeedTone, InkStart, ItemFeed};
use crate::core::livesplit::{RunView, FRESH_RUN_MAX_IGT_MS};
use crate::core::map_utils::format_map_id;
use crate::core::memory_effects::{MemoryEffect, MemoryEffects, MemoryState};
use crate::core::play_clock::PlayClock;
use crate::core::protocol::{
    CameraVariant, CharacterState, ConditionKind, ExitInfo, ItemBanner, ItemEffectPayload,
    ItemReminder, ParticipantInfo, ParticipantStatus, RaceInfo, RaceItemEntry, RaceItemGoods,
    RaceStatus, RelayInfo, RelayMember, RelayRole, SeedInfo, TalismanFlag,
};
use crate::core::relay::{self, CaptureInFlight, FlagWarp, PendingRelease, WarpStep};
use crate::core::relay_items;
use crate::core::timed_effects::TimedEffects;
use crate::core::types::PlayerPosition;

// =============================================================================
// CONNECTION / MESSAGES (moved from dll/websocket.rs)
// =============================================================================

/// Connection status
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionStatus {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Error,
}

/// Messages from the WS worker thread to the state machine.
///
/// The WS thread constructs these from `ServerMessage`s; the shell may enrich
/// them before delegation (`RaceStatusChange::current_igt` is always `None`
/// on the wire and filled by the shell with a fresh IGT read, so the
/// machine's freeze decision needs no game access).
#[derive(Debug)]
pub enum MachineMessage {
    StatusChanged(ConnectionStatus),
    AuthOk {
        participant_id: String,
        race: RaceInfo,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
        /// User's equipped phantom skin name, or None when not equipped or
        /// when the server sent the literal "none". Resolved to SpEffect IDs
        /// at apply-time via `seed.phantom_skins[name]`.
        phantom_skin: Option<String>,
        /// Server release version when a newer compatible mod build exists.
        latest_mod_version: Option<String>,
        /// Race item key the server says the runner holds, confirmed or not.
        held_item: Option<String>,
        /// The runner's relay team; `None` on any other race.
        relay: Option<RelayInfo>,
    },
    AuthError(String),
    RaceStart(u32),
    LeaderboardUpdate {
        participants: Vec<ParticipantInfo>,
        leader_splits: Option<HashMap<i32, i32>>,
    },
    RaceStatusChange {
        status: RaceStatus,
        /// Filled by the shell at delegation time (fresh `read_igt`), never
        /// by the WS thread. Consumed by the finish-freeze decision.
        current_igt: Option<u32>,
    },
    /// Server pushed a refreshed RaceInfo (race_ends_at extension, etc.).
    /// Replaces the cached race info wholesale.
    RaceInfoUpdate(RaceInfo),
    PlayerUpdate(ParticipantInfo),
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        original_tier: Option<i32>,
        layer: Option<i32>,
        is_first_visit: bool,
        exits: Vec<ExitInfo>,
        unused_exits: Option<u32>,
        defeat_flag: Option<u32>,
        message_id: Option<u64>,
    },
    /// Aggregated death counts per zone for death marker flags
    DeathCounts(HashMap<String, u32>),
    /// Event flag drained from outgoing channel on reconnect, must be re-buffered
    RequeueEventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    EventFlagAck {
        message_id: u64,
    },
    /// Zone query drained from outgoing channel on reconnect, must be re-buffered
    RequeueZoneQuery {
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
        quit_out: bool,
    },
    ZoneQueryAck {
        message_id: u64,
    },
    Error {
        message: String,
        code: Option<ConditionKind>,
    },
    /// Server rejected permanently (4xxx close code or auth failure). Stop reconnecting.
    PermanentError(String),
    /// A race item granted to the local runner: spawn its goods once the
    /// player is loaded, announce it, answer `item_received`.
    ItemGrant {
        grant_id: u64,
        item: String,
        banner: ItemBanner,
    },
    /// A race item effect aimed at the local runner, applied once the player
    /// is loaded. Without a banner for the runner's own self item, whose
    /// `ItemResult` carries it.
    ItemEffect {
        item: String,
        effect: ItemEffectPayload,
        banner: Option<ItemBanner>,
        reminder: Option<ItemReminder>,
    },
    /// The outcome of the local runner's item use.
    ItemResult {
        item: String,
        banner: ItemBanner,
        reminder: Option<ItemReminder>,
    },
    /// Take a race goods back: raise its removal flag.
    ItemRemove {
        goods: String,
        banner: Option<ItemBanner>,
    },
    /// A banner with nothing applied: a Star holder's block.
    ItemNotice {
        banner: ItemBanner,
    },
    /// The relay team's state, replaced whole.
    RelayUpdate(RelayInfo),
    /// The server asks the holder for its state: a handoff to `to_name`.
    RelayRelease {
        handoff_id: String,
        to_name: String,
    },
    /// The server refused a relay request: `message` is shown, `code` logged.
    RelayRefused {
        code: String,
        message: String,
    },
}

// =============================================================================
// STATE TYPES (moved from dll/tracker.rs)
// =============================================================================

/// Zone update data received from server
#[derive(Debug, Clone)]
pub struct ZoneUpdateData {
    pub display_name: String,
    pub tier: Option<i32>,
    pub original_tier: Option<i32>,
    pub layer: Option<i32>,
    #[allow(dead_code)] // Kept for future use (e.g., spectator UI)
    pub is_first_visit: bool,
    pub exits: Vec<ExitInfo>,
    /// Exits no edge takes; `None` on a seed older than graph.json 4.13.
    pub unused_exits: Option<u32>,
    /// The zone's boss defeat flag (one of `boss_flags`), `None` when the
    /// zone is no boss arena the mod watches.
    pub defeat_flag: Option<u32>,
}

/// A coded server condition, displayed while fresh (the server re-sends
/// it on every rejected message, ~1/s, while the condition holds).
#[derive(Debug, Clone)]
pub struct ServerCondition {
    pub kind: ConditionKind,
    pub message: String,
    pub last_seen: Instant,
}

#[derive(Debug, Clone, Copy)]
pub struct BufferedEventFlag {
    pub flag_id: u32,
    pub igt_ms: u32,
}

#[derive(Debug, Clone)]
pub struct BufferedZoneQuery {
    pub igt_ms: u32,
    pub grace_entity_id: Option<u32>,
    pub map_id: Option<String>,
    pub position: Option<[f32; 3]>,
    pub play_region_id: Option<u32>,
    pub quit_out: bool,
}

/// Current race state from server
#[derive(Debug, Clone, Default)]
pub struct RaceState {
    pub race: Option<RaceInfo>,
    pub seed: Option<SeedInfo>,
    pub participants: Vec<ParticipantInfo>,
    pub leader_splits: Option<HashMap<i32, i32>>,
    pub race_started_at: Option<Instant>,
    pub countdown_end: Option<Instant>,
    pub current_zone: Option<ZoneUpdateData>,
    pub death_counts: HashMap<String, u32>,
}

/// Cached frame-local memory reads reused by update and rendering.
#[derive(Debug, Clone, Copy, Default)]
pub struct FrameSnapshot {
    pub igt_ms: Option<u32>,
    pub death_count: Option<u32>,
    pub position_readable: bool,
    /// Whether the engine's "world clock stopped" byte is set (`None` =
    /// not read this frame or unreadable). Stands in for "loading screen
    /// displayed" outside frozen-clock seeds; see the reveal logic.
    pub loading_screen: Option<bool>,
    /// Direct screen signal (CSMenuManImp): `Some(true)` = in game,
    /// `Some(false)` = loading screen or main menu, `None` = signal
    /// unavailable (unmapped build) or not read this frame.
    pub screen_in_game: Option<bool>,
    /// Blackscreen fade while in game (SoulSplitter's IsBlackscreenActive).
    /// `None` follows `screen_in_game`.
    pub blackscreen: Option<bool>,
    /// Watched debug flags that are on (`core::debug_flags` mask). `None` =
    /// not read this frame or unreadable.
    pub debug_flags: Option<u32>,
    /// Map id of the loaded position, read with the readability check every
    /// frame; `None` while the position is unreadable.
    pub map_id: Option<u32>,
    /// Current HP (`None` = not read this frame or unreadable).
    pub hp: Option<i32>,
}

// =============================================================================
// TICK INTERFACES
// =============================================================================

/// What the machine wants read from the game this frame (two-phase tick:
/// the shell calls `pre_tick`, performs exactly these reads, then `tick`).
#[derive(Debug, Clone, Copy, Default)]
pub struct FrameNeeds {
    pub igt: bool,
    pub deaths: bool,
    /// Read the loading byte (only while a zone reveal is pending).
    pub loading: bool,
    /// Read the screen-state/blackscreen chains (mid-run for the IGT
    /// freeze, or while a zone reveal is pending).
    pub blackscreen: bool,
    pub poll_flags: bool,
    /// Read the game's debug-flag bytes (cheat detection, 10 Hz while racing).
    pub debug_flags: bool,
    /// Read the player's HP (only while a relay runner's warp waits on it).
    pub hp: bool,
}

/// Inputs to one tick, gathered by the shell.
#[derive(Debug, Default)]
pub struct TickInput {
    pub snapshot: FrameSnapshot,
    pub connected: bool,
    /// Captured grace entity id from the warp hook (loading-exit frames only).
    pub warp_capture: Option<u32>,
    /// Player position (loading-exit frames only), for zone queries.
    pub position: Option<PlayerPosition>,
    /// `(flag_id, is_set)` for every readable flag in `event_ids`, then for
    /// the boss defeat flags `boss_flags_to_read` names this scan (called
    /// after the frame's last `handle_message`: the tick moves the rotation
    /// past that window), then for the race item use flags
    /// `item_use_flags_to_read` names. `Some` when the shell performed reads this frame
    /// (`wants_flag_reads`), `None` otherwise. Unreadable flags are omitted
    /// from the vec.
    pub flag_reads: Option<Vec<(u32, bool)>>,
    /// Weapons for the status_update, read by the shell only when
    /// `wants_status_update` said one may fire this frame.
    pub weapons: [Option<i32>; 2],
    /// Whether the flag reader diagnosed OK (None = flags not read).
    pub flag_reader_ok: Option<bool>,
}

/// Side effects for the shell to execute, in order.
#[derive(Debug, PartialEq)]
pub enum Effect {
    SendReady,
    /// Tell the server whether this relay runner is loaded at the Chapel with
    /// its lock raised (readiness does not survive the socket).
    SendRelayReady {
        ready: bool,
    },
    /// Capture the character's state on the shell's worker thread; the
    /// result comes back through `RaceMachine::relay_state_captured` with the
    /// same `handoff_id` (`None` for a zone checkpoint).
    CaptureRelayState {
        handoff_id: Option<String>,
    },
    /// Send a captured state: the answer to a release (`handoff_id` set) or
    /// a checkpoint (`None`), already fitted to the wire caps.
    SendRelayState {
        handoff_id: Option<String>,
        state: CharacterState,
        igt_ms: u32,
    },
    SendStatusUpdate {
        igt_ms: u32,
        death_count: u32,
        weapons: [Option<i32>; 2],
        /// Cumulative debug-flag mask since the race start.
        debug_flags: u32,
    },
    SendEventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    SendZoneQuery {
        igt_ms: u32,
        message_id: u64,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        quit_out: bool,
    },
    /// Write a flag value into game memory (the shell resolves the category
    /// first and skips the write when unresolvable, as today).
    SetGameFlag {
        flag_id: u32,
        value: bool,
    },
    /// Add a quit-out penalty to the in-game timer (4-byte u32 write; see
    /// `GameState::add_igt_penalty`).
    ApplyIgtPenalty {
        ms: u32,
    },
    /// Blackscreen freeze write-back: overwrite the in-game timer with the
    /// frozen value (see `GameState::write_igt`). Emitted every fade frame.
    FreezeIgt {
        ms: u32,
    },
    /// Clear the warp hook's captured grace entity id.
    ClearWarpCapture,
    /// Spawn runtime items; the shell re-checks its own guards
    /// (items_spawned atomic, spawner thread liveness) exactly as today.
    SpawnItems,
    /// Start the phantom-skin runner; the shell applies its existing
    /// already-running / same-skin guards and owns the thread + stop flag.
    /// `speffects` comes from the seed catalog, resolved by the machine.
    StartPhantomSkin {
        name: String,
        speffects: Vec<i32>,
    },
    /// The run as the LiveSplit driver sees it, emitted when its liveness,
    /// attempt or arrivals change, and only for a seed with flag layers.
    LiveSplitRun(Box<RunView>),
    /// Save the event flags the server has not acknowledged yet, so the next
    /// launch can send them if this process dies first. Emitted only when the
    /// set changes; an empty list means nothing is left to save.
    PersistUnackedFlags(UnackedFlags),
    /// Ready the game access race item effects need (the SpEffect apply
    /// function's pattern scan) on a background thread, so the first effect
    /// does not stall a frame. Emitted at every auth_ok of a race with
    /// items; the shell runs it once per process.
    PrewarmRaceItems,
    /// Write `icon_id` into the `EquipParamGoods` row of `goods_id`, so the
    /// goods shows the held item's icon in game. Emitted before a grant's
    /// spawn and, for the held item, before each inventory report (a game
    /// restart reloads the params); the shell logs a write it cannot make
    /// yet (params not indexed) and the next one makes it.
    SetGoodsIcon {
        goods_id: u32,
        icon_id: u16,
    },
    /// Give a granted race item: the shell spawns its goods unless the
    /// inventory already holds them, then answers `item_received`, and hands
    /// the outcome back through `RaceMachine::grant_spawn_result`.
    SpawnRaceItem {
        grant_id: u64,
        goods_id: u32,
    },
    /// Answer `item_received` for a grant this process already handled.
    SendItemReceived {
        grant_id: u64,
    },
    /// Report the race goods held: the shell reads each goods' quantity,
    /// sends `item_inventory` with the goods keys of those above 0 and hands
    /// them back through `RaceMachine::inventory_read`. `goods` pairs every
    /// catalog goods key with its goods id.
    ReportItemInventory {
        goods: Vec<(String, u32)>,
    },
    /// Apply a SpEffect to the player. `left_ms`: a timed application
    /// with that much time left (a fresh one gets its full duration, one
    /// applied again at a loading exit what is left of it); `None`: an
    /// instant one, applied as its row says.
    ApplySpEffect {
        speffect_id: u32,
        left_ms: Option<u32>,
    },
    /// Damage the player along the race item damage curve
    /// (`core::item_damage`), computed from the HP at application.
    ApplyItemDamage {
        base_pct: u8,
        floor_pct: u8,
        tail_pct: u8,
    },
    /// Set the SpEffect's max equip load rate so the player's current load
    /// sits at `load_pct` percent of the max (`core::equip_load`), then
    /// apply it, timed as `ApplySpEffect` is. Applied again at a loading
    /// exit, it comes back as an `ApplySpEffect`: the rate stays in its row.
    ApplyEquipLoad {
        speffect_id: u32,
        load_pct: u8,
        left_ms: Option<u32>,
    },
    /// Write the memory race item effects: every field of `state`, a `None`
    /// or `false` field as the game's default (see `MemoryState`). Walk the
    /// characters around to hide or show the foes only when `walk_foes`.
    ApplyMemoryState {
        state: MemoryState,
        walk_foes: bool,
    },
    /// Take one of the talismans the player wears (the Talisman Thief): the
    /// shell reads the talisman slots, picks one with
    /// `core::talisman_thief::pick_talisman` and raises its flag (the seed's
    /// event removes it), then hands the id taken, or `None`, to
    /// `RaceMachine::talisman_steal_result` and executes what it returns.
    StealTalisman {
        talismans: Vec<TalismanFlag>,
        roll: u32,
        report_id: u64,
    },
    /// Give the player a talisman (the thief's gift).
    SpawnTalisman {
        talisman_id: u32,
    },
    /// Give the player the junk weapon and equip it in the right hand in use
    /// (`core::item_inventory::junk_slot`), unless that hand already holds it
    /// (`junk_is_free`); the copy equipped is the one the give added
    /// (`new_copy`).
    EquipJunkWeapon {
        weapon_id: u32,
    },
    /// Spawn the Hunter behind the player; the shell answers
    /// `RaceMachine::hunter_request_result`.
    RequestHunter {
        chr_id: u32,
        npc_param_id: u32,
        think_id: u32,
    },
    /// Look for a live character of the Hunter's NpcParam row; the shell
    /// answers `RaceMachine::hunter_seen`.
    FindHunter {
        npc_param_id: u32,
    },
    /// End the Hunter: clear a spawn still pending and bring every live
    /// character of that NpcParam row to 0 HP.
    EndHunter {
        npc_param_id: u32,
    },
    /// Send `item_report`: the outcome of a steal or of a Hunter.
    SendItemReport {
        report_id: u64,
        landed: bool,
        talisman_id: Option<u32>,
    },
}

/// A granted race item on its way to the inventory (see `pending_grants`):
/// the item, the goods it is held as and the icon id written into that
/// goods' row.
#[derive(Debug)]
struct PendingGrant {
    grant_id: u64,
    item: String,
    goods_id: u32,
    icon_id: u16,
    banner: FeedBanner,
}

/// What a race item effect does once applied.
#[derive(Debug)]
enum ItemAction {
    /// Executed by the shell (`ApplySpEffect`, `ApplyItemDamage`,
    /// `ApplyEquipLoad`, `StealTalisman`, `SpawnTalisman`,
    /// `EquipJunkWeapon`).
    Shell(Effect),
    /// Overlay only: exit destinations stay hidden this long.
    Ink(Duration),
    /// Written into the game's memory this long (see
    /// `RaceMachine::maintain_memory_effects`).
    Memory(MemoryEffect, Duration),
    /// The Lightning: the timed SpEffect `speffect_id` (its slow walk) and
    /// the memory scale `scale`, both this long.
    Lightning {
        speffect_id: u32,
        scale: f32,
        duration: Duration,
    },
    /// The Hunter, sent out through `RaceMachine::maintain_hunter`; his
    /// banner and reminder wait in him until he is found.
    Hunter(HunterSpec),
}

/// A race item effect waiting for a loaded frame: its banner (none for the
/// runner's own self item) and its reminder, drawn with `icon`.
#[derive(Debug)]
struct PendingItemEffect {
    action: ItemAction,
    banner: Option<FeedBanner>,
    icon: String,
    reminder: Option<ItemReminder>,
}

// =============================================================================
// RACE MACHINE
// =============================================================================

use std::collections::HashSet;
use std::time::Duration;
use tracing::{debug, error, info, warn};

use crate::core::flag_buffer::{FlagBuffer, UnackedFlag, UnackedFlags, SAVE_RELOAD_IGT_DROP_MS};

/// Pure race state machine. Owns every piece of plain-data race state and
/// makes every decision; performs no IO. Fields are `pub` so the Windows
/// shell and renderer can read them directly (writes go through
/// `handle_message`/`tick`, except the per-frame `frame_snapshot` which the
/// shell refreshes before each tick).
pub struct RaceMachine {
    pub race_state: RaceState,
    pub my_participant_id: Option<String>,
    pub my_participant_index: Option<usize>,
    /// The runner's relay team and role, replaced whole by `auth_ok` and
    /// `relay_update`; `None` on a race without relay. On a relay race the
    /// leaderboard rows are teams, so the runner's row is `relay.team_id`
    /// (see `my_row_id`).
    relay: Option<RelayInfo>,
    pub event_ids: Vec<u32>,
    pub triggered_flags: HashSet<u32>,
    pub flag_buffer: FlagBuffer,
    pub in_flight_event_flags: HashMap<u64, BufferedEventFlag>,
    pub in_flight_zone_queries: HashMap<u64, BufferedZoneQuery>,
    pub next_event_message_id: u64,
    /// finish_event from server, sent immediately (no loading screen on boss kill)
    pub finish_event: Option<u32>,
    /// Boss defeat flags from the seed, sorted and deduplicated (membership
    /// by binary search, a stable read rotation), replaced on every auth_ok.
    /// One-shot like `finish_event` (`triggered_flags`), never cleared in
    /// game memory (see `capture_boss_kill`).
    pub boss_flags: Vec<u32>,
    /// Index in `boss_flags` where the next scan's boss reads start (see
    /// `boss_flags_to_read`).
    boss_read_cursor: usize,
    /// Use flags of the seed catalog's goods, sorted and deduplicated
    /// (membership by binary search), replaced on every auth_ok. The game
    /// raises one on every use: see `capture_item_use`.
    pub item_use_flags: Vec<u32>,
    /// Every catalog goods key with its goods id, sorted by key, replaced on
    /// every auth_ok: what an inventory report covers.
    item_inventory_goods: Vec<(String, u32)>,
    /// Race item key the runner holds as far as this process knows: named by
    /// auth_ok (a restarted process learns it there) and by each grant,
    /// forgotten when its goods is used or removed, at an item result and at
    /// a new start. Its goods' icon is written again before each inventory
    /// report, and the held row follows it (`inventory_read`).
    held_item: Option<String>,
    /// Grants whose goods this process gave (or found already held): one
    /// the server sends again is only acknowledged.
    handled_grants: HashSet<u64>,
    /// Grants and item effects received, waiting for a loaded frame (see
    /// `flush_race_items`).
    pending_grants: Vec<PendingGrant>,
    /// Grants handed to the shell this frame, until it reports the spawn
    /// outcome (`grant_spawn_result`).
    spawning_grants: Vec<PendingGrant>,
    /// Grants whose spawn failed, retried at the next game load or
    /// reconnection rather than on every frame.
    retry_grants: Vec<PendingGrant>,
    pending_item_effects: Vec<PendingItemEffect>,
    /// Race item banners, reminder rows and ink timer, for the overlay.
    item_feed: ItemFeed,
    /// Wall time while the player's position is readable: what times the
    /// reminder rows, the ink and the timed effects, so a load does not
    /// eat their time.
    play_clock: PlayClock,
    /// Timed SpEffects the race items applied, applied again with their
    /// time left at each loading exit (the game drops them at a load).
    timed_effects: TimedEffects,
    /// Memory race item effects (Vanish, Unseen Foes, Slow-mo, Giant, Camera,
    /// the Lightning's shrink) on the play clock; `maintain_memory_effects` writes them.
    memory_effects: MemoryEffects,
    /// The reminder text of the last memory effect started, per kind: the
    /// next one of the kind (a Giant on another, a Camera on another
    /// variant) replaces that effect, so its row goes. The Lightning's
    /// shrink records none: its row is its slow walk's.
    memory_reminders: Vec<(Discriminant<MemoryEffect>, String)>,
    /// The memory state last handed to the shell (the default until an
    /// effect: the game's own), and when; with the last foes walk.
    memory_written: MemoryState,
    memory_written_at: Instant,
    foes_walked_at: Instant,
    /// Index of the runner's own entry in `relay.members`, found once per
    /// `set_relay` so the per-frame predicates do no scan and no compare.
    relay_member: Option<usize>,
    /// What this process last wrote to the relay lock flag (`None` before
    /// any write): the flag is saved, so the machine knows no more than the
    /// server's word and its own writes.
    relay_lock: Option<bool>,
    /// When `relay_lock` last turned on (the start of the locked stretch).
    relay_lock_since: Option<Instant>,
    /// The lock was written (or found already right) since the last loading
    /// exit: a load can bring back a save with another value.
    relay_asserted: bool,
    /// The warp to the Chapel being made, if any.
    relay_warp: Option<FlagWarp>,
    /// A warp that failed is not made again until a loading exit.
    relay_warp_given_up: bool,
    /// Warps of the current locked stretch whose load ended away from the
    /// Chapel; `relay::WARP_LANDINGS_MAX` of them end the return for good.
    /// A loading exit does not reset it: the Chapel reached, or the lock
    /// going down, does.
    relay_warp_landings: u32,
    /// A warp ended by a load: where the next loading exit lands is counted.
    relay_landing_due: bool,
    /// The `relay_ready` value last sent on this socket (`None` = none yet:
    /// readiness does not survive the socket).
    relay_ready_sent: Option<bool>,
    /// The holder's gates are locked (the cap), and its banner is due.
    relay_capped: bool,
    relay_cap_due: bool,
    /// A `relay_release` waiting for its capture and its answer.
    relay_release: Option<PendingRelease>,
    /// The capture asked of the shell and not yet answered (one at a time).
    relay_capture: Option<CaptureInFlight>,
    /// A zone was revealed to a connected live holder this frame: a
    /// checkpoint capture is wanted if none is in flight.
    relay_checkpoint_due: bool,
    /// The recipient of the last answered release and when it was answered:
    /// the banner waits for the server's flip.
    relay_passed: Option<(String, Instant)>,
    /// The Hunter sent after this runner (`maintain_hunter`).
    hunter: Hunter,
    /// The text of the reminder row his `Found` added: the row goes when he
    /// is gone or ended, whatever time it had left.
    hunter_row: Option<String>,
    /// The last loading exit: a Hunter spawns once the player has been
    /// loaded `hunter::SETTLE` since (none seen yet: settled).
    last_loading_exit: Option<Instant>,
    pub last_status_update: Instant,
    pub last_flag_poll: Instant,
    pub ready_sent: bool,
    /// Temporary status message (yellow banner, auto-expires after 3s)
    pub status_message: Option<(String, Instant)>,
    /// Update-available notice (gold line, auto-expires after 10s)
    pub update_notice: Option<(String, Instant)>,
    /// Last flag reader status discriminant (for transition logging)
    pub last_flag_reader_ok: Option<bool>,
    /// Zone update received, waiting for the loading screen to end before
    /// revealing
    pub pending_zone_update: Option<ZoneUpdateData>,
    /// When the pending zone update was received; anchors the defensive
    /// reveal timeout and the one-shot stall-warn diagnostic
    pub pending_zone_received_at: Option<Instant>,
    /// Snapshot of current_layer taken when leaderboard_update bumps the layer.
    pub pre_reveal_layer: Option<i32>,
    /// One-shot latch for the stall-warn diagnostic, reset on each
    /// zone_update receipt
    pub zone_stall_warned: bool,
    /// Whether position was readable last frame (loading screen exit detection)
    pub was_position_readable: bool,
    /// Quit-out observed; consumed (penalty + zone tag) at the next loading exit.
    pub pending_quit_out: bool,
    /// Has been in-world since race start (or boot, before the first race
    /// start). Guards quit-out arming against boot-time and pre-start save
    /// juggling; cleared on `RaceStart` so a quit-out from before the start
    /// cannot leak a penalty into the first in-race load.
    pub has_been_in_world: bool,
    /// Wrong save loaded (impossible IGT forward jump across an unload):
    /// freeze all race interaction (sends, flag reads/writes, penalty) and
    /// show the persistent banner until the race save returns. This is a
    /// local, IGT-derived heuristic, independent of the server-pushed
    /// `ConditionKind::WrongSave` condition below (same real-world cause,
    /// different detection path).
    pub wrong_save: bool,
    /// Last IGT observed on the believed-good save and when: the recovery
    /// baseline while `wrong_save` is set.
    pub last_good_igt: Option<u32>,
    pub last_good_at: Option<Instant>,
    /// Death count last observed on the frame snapshot: the baseline for
    /// the deathless death edge. `None` until the first readable frame, so
    /// a mid-race (re)start records a baseline instead of a false death.
    pub last_seen_death_count: Option<u32>,
    /// One-shot latch for the deathless "You died" banner; reset on
    /// `RaceStart`.
    pub deathless_banner_shown: bool,
    /// Watched debug flags seen since the race start (cumulative mask, see
    /// `core::debug_flags`); reported with every status_update.
    pub debug_flags_seen: u32,
    /// Last debug-flag mask read while racing; `None` while the read gate is
    /// closed. Drives the cheat banner and the change log.
    pub debug_flags_last: Option<u32>,
    pub last_debug_flags_poll: Instant,
    /// Seed mismatch: config seed_id doesn't match server seed_id
    pub seed_mismatch: bool,
    /// Last auth error message from server (see dll handler ordering guarantee)
    pub last_auth_error: Option<String>,
    /// Permanent error from server (persistent red banner, no auto-dismiss)
    pub permanent_error: Option<String>,
    /// Most recent coded server condition (see `ConditionKind`), displayed
    /// while fresh via `get_blocking_condition`/`get_waiting_line`.
    pub server_condition: Option<ServerCondition>,
    /// IGT frozen when the race ends before the local player finishes
    pub frozen_igt_ms: Option<u32>,
    /// Last observed IGT, used to detect save reloads. Unlike
    /// `last_good_igt` it keeps updating through wrong-save episodes and
    /// survives `RaceStart`, so the per-save flush still catches a stale
    /// setup-phase save on the first in-race observation.
    pub last_observed_igt: Option<u32>,
    /// Blackscreen freeze baseline: last IGT seen outside a freezable
    /// fade. During a fade the timer is rewritten to this value every
    /// frame (SoulSplitter's `_inGameTime`).
    pub freeze_last_igt: Option<u32>,
    /// Cached reads for the current frame (written by the shell each frame)
    pub frame_snapshot: FrameSnapshot,
    /// Bumped on every zone reveal; the shell's exits render cache keys on it.
    pub zone_version: u64,
    pub leaderboard_version: u64,
    pub last_sent_debug: Option<String>,
    pub last_received_debug: Option<String>,
    /// Seed id from the local pack config, for stale-pack detection
    pub config_seed_id: String,
    /// Training mode: the server auto-starts, so `ready` is never sent.
    pub training: bool,
    /// First IGT on each layer in this attempt, `total_layers + 1` long (see
    /// `RunView::arrivals`). Only `record_arrival` records an arrival; auth
    /// sizes it and a new attempt clears it.
    run_arrivals: Vec<Option<u32>>,
    /// Changes with every new attempt at the run (see `RunView::attempt`).
    run_attempt: u32,
    /// The arrivals or the attempt changed since the last `LiveSplitRun`.
    run_view_changed: bool,
    /// `live` of the last `LiveSplitRun`.
    run_view_live: bool,
    /// Unacknowledged flags a previous launch saved, held until this launch
    /// knows the participant and the IGT of the loaded save
    /// (`release_restored_flags`).
    pub restored_flags: Option<UnackedFlags>,
    /// First in-game IGT of this process: the save loaded at launch, against
    /// which restored flags are judged.
    pub first_observed_igt: Option<u32>,
    /// Restored flags reached the buffers after `ready` went out: send them
    /// without waiting for a reconnection.
    pub flush_restored: bool,
    /// Fingerprint of the unacknowledged flags last handed to the shell for
    /// saving (0 = nothing saved), so an unchanged set costs no write.
    pub persisted_fingerprint: u64,
}

/// Order-independent fingerprint of a set of unacknowledged flags, 0 when
/// the set is empty.
fn unacked_fingerprint(flags: impl Iterator<Item = UnackedFlag>) -> u64 {
    flags.fold(0u64, |acc, flag| {
        // splitmix64 finalizer over the packed fields.
        let mut z = ((flag.flag_id as u64) << 32 | flag.igt_ms as u64)
            ^ flag
                .message_id
                .map_or(0, |id| id.rotate_left(17) ^ 0x9E37_79B9_7F4A_7C15);
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        acc.wrapping_add(z ^ (z >> 31))
    })
}

impl RaceMachine {
    /// `seed_message_id`: initial value for the message-id counter (the shell
    /// seeds it from wall-clock millis so ids stay unique across sessions).
    pub fn new(seed_message_id: u64, config_seed_id: String, training: bool, now: Instant) -> Self {
        Self {
            race_state: RaceState::default(),
            my_participant_id: None,
            my_participant_index: None,
            relay: None,
            event_ids: Vec::new(),
            triggered_flags: HashSet::new(),
            flag_buffer: FlagBuffer::default(),
            in_flight_event_flags: HashMap::new(),
            in_flight_zone_queries: HashMap::new(),
            next_event_message_id: seed_message_id,
            finish_event: None,
            boss_flags: Vec::new(),
            boss_read_cursor: 0,
            item_use_flags: Vec::new(),
            item_inventory_goods: Vec::new(),
            held_item: None,
            handled_grants: HashSet::new(),
            pending_grants: Vec::new(),
            spawning_grants: Vec::new(),
            retry_grants: Vec::new(),
            pending_item_effects: Vec::new(),
            item_feed: ItemFeed::new(),
            play_clock: PlayClock::default(),
            timed_effects: TimedEffects::default(),
            memory_effects: MemoryEffects::default(),
            memory_reminders: Vec::new(),
            memory_written: MemoryState::default(),
            memory_written_at: now,
            foes_walked_at: now,
            relay_member: None,
            relay_lock: None,
            relay_lock_since: None,
            relay_asserted: false,
            relay_warp: None,
            relay_warp_given_up: false,
            relay_warp_landings: 0,
            relay_landing_due: false,
            relay_ready_sent: None,
            relay_capped: false,
            relay_cap_due: false,
            relay_release: None,
            relay_capture: None,
            relay_checkpoint_due: false,
            relay_passed: None,
            hunter: Hunter::default(),
            hunter_row: None,
            last_loading_exit: None,
            last_status_update: now,
            last_flag_poll: now,
            ready_sent: false,
            status_message: None,
            update_notice: None,
            last_flag_reader_ok: None,
            pending_zone_update: None,
            pending_zone_received_at: None,
            pre_reveal_layer: None,
            zone_stall_warned: false,
            was_position_readable: true,
            pending_quit_out: false,
            has_been_in_world: false,
            wrong_save: false,
            last_good_igt: None,
            last_good_at: None,
            last_seen_death_count: None,
            deathless_banner_shown: false,
            debug_flags_seen: 0,
            debug_flags_last: None,
            last_debug_flags_poll: now,
            seed_mismatch: false,
            last_auth_error: None,
            permanent_error: None,
            server_condition: None,
            frozen_igt_ms: None,
            last_observed_igt: None,
            freeze_last_igt: None,
            frame_snapshot: FrameSnapshot::default(),
            zone_version: 0,
            leaderboard_version: 0,
            last_sent_debug: None,
            last_received_debug: None,
            config_seed_id,
            training,
            run_arrivals: Vec::new(),
            run_attempt: 0,
            run_view_changed: false,
            run_view_live: false,
            restored_flags: None,
            first_observed_igt: None,
            flush_restored: false,
            persisted_fingerprint: 0,
        }
    }

    /// Hand over the unacknowledged flags a previous launch saved.
    pub fn restore_unacked(&mut self, saved: UnackedFlags) {
        if saved.flags.is_empty() {
            return;
        }
        // Already on disk: no write until the set changes.
        self.persisted_fingerprint = unacked_fingerprint(saved.flags.iter().copied());
        // A PC clock set back between launches would otherwise let a new
        // message reuse a restored id, and the server take it for the old one.
        if let Some(last_id) = saved.flags.iter().filter_map(|flag| flag.message_id).max() {
            self.next_event_message_id = self.next_event_message_id.max(last_id.saturating_add(1));
        }
        self.restored_flags = Some(saved);
    }

    /// The server's id of the run's current attempt (`RaceInfo::attempt_id`,
    /// refreshed by the `race_info_update` of a race start), None from an
    /// older server. Saved with the unacknowledged flags, so a relaunch drops
    /// those of an attempt since reset.
    fn attempt_id(&self) -> Option<&str> {
        self.race_state.race.as_ref()?.attempt_id.as_deref()
    }

    /// Every flag the server has not acknowledged: restored from disk,
    /// buffered (deferred or pending), or in flight.
    fn unacked_flags(&self) -> impl Iterator<Item = UnackedFlag> + '_ {
        let restored = self
            .restored_flags
            .iter()
            .flat_map(|saved| saved.flags.iter().copied());
        let buffered = self
            .flag_buffer
            .iter()
            .map(|&(flag_id, igt_ms)| UnackedFlag {
                flag_id,
                igt_ms,
                message_id: None,
            });
        let in_flight = self
            .in_flight_event_flags
            .iter()
            .map(|(&message_id, flag)| UnackedFlag {
                flag_id: flag.flag_id,
                igt_ms: flag.igt_ms,
                message_id: Some(message_id),
            });
        restored.chain(buffered).chain(in_flight)
    }

    /// Hand the unacknowledged flags to the shell for saving when they
    /// changed since the last save. Runs at the end of every tick and
    /// message.
    fn persist_unacked_if_changed(&mut self, effects: &mut Vec<Effect>) {
        // Per-frame path: nothing unacknowledged and nothing on disk.
        if self.persisted_fingerprint == 0
            && self.restored_flags.is_none()
            && self.flag_buffer.is_empty()
            && self.in_flight_event_flags.is_empty()
        {
            return;
        }
        let Some(participant_id) = self.my_participant_id.as_ref() else {
            return;
        };
        crate::profile_span!("persist_unacked");
        let fingerprint = unacked_fingerprint(self.unacked_flags());
        if fingerprint == self.persisted_fingerprint {
            return;
        }
        self.persisted_fingerprint = fingerprint;
        let mut flags: Vec<UnackedFlag> = self.unacked_flags().collect();
        flags.sort_unstable_by_key(|flag| (flag.igt_ms, flag.message_id, flag.flag_id));
        effects.push(Effect::PersistUnackedFlags(UnackedFlags {
            participant_id: participant_id.clone(),
            attempt_id: self.attempt_id().map(str::to_owned),
            flags,
        }));
    }

    /// Move the flags a previous launch saved into this launch's buffers,
    /// once the participant is known and a save is loaded. Dropped: another
    /// participant's flags, those of another attempt (the race was reset and
    /// run again, or the Set Seed run was reset), those of a race no longer
    /// running or a run already finished, and a flag captured 60 s or more
    /// after the loaded save's IGT (a backup restore: the traversal is not in
    /// that save; same bound as the per-save flush). A kept capture feeds the
    /// LiveSplit depth tracker like a fresh one.
    fn release_restored_flags(&mut self, now: Instant) {
        let Some(saved) = self.restored_flags.as_ref() else {
            return;
        };
        let Some(me) = self.my_participant_id.as_deref() else {
            return;
        };
        if saved.participant_id != me {
            info!(
                saved_for = %saved.participant_id,
                "[RACE] Saved event flags belong to another participant, dropped"
            );
            self.restored_flags = None;
            return;
        }
        if saved.attempt_id.as_deref() != self.attempt_id() {
            info!(
                saved_attempt = ?saved.attempt_id,
                attempt = ?self.attempt_id(),
                "[RACE] Saved event flags belong to another attempt, dropped"
            );
            self.restored_flags = None;
            return;
        }
        let Some(save_igt) = self.first_observed_igt else {
            return;
        };
        let Some(saved) = self.restored_flags.take() else {
            return;
        };
        if !self.is_race_running() || self.am_i_finished() {
            info!(
                count = saved.flags.len(),
                "[RACE] Saved event flags dropped (race over or run finished)"
            );
            return;
        }
        let mut kept = 0;
        for flag in saved.flags {
            if crate::core::flag_buffer::detect_save_reload(Some(flag.igt_ms), save_igt) {
                info!(
                    flag_id = flag.flag_id,
                    flag_igt_ms = flag.igt_ms,
                    save_igt_ms = save_igt,
                    "[RACE] Saved event flag dropped (not in the loaded save)"
                );
                continue;
            }
            // The finish and boss defeat flags stay set in the save: without
            // this, the next scan would report them again at the current IGT.
            if self.finish_event == Some(flag.flag_id)
                || self.boss_flags.binary_search(&flag.flag_id).is_ok()
            {
                self.triggered_flags.insert(flag.flag_id);
            }
            match flag.message_id {
                Some(message_id) => {
                    self.in_flight_event_flags.insert(
                        message_id,
                        BufferedEventFlag {
                            flag_id: flag.flag_id,
                            igt_ms: flag.igt_ms,
                        },
                    );
                }
                None => self.flag_buffer.add_pending(flag.flag_id, flag.igt_ms),
            }
            // Never captured by this process: without it, its depth would
            // be a skipped split until the next auth_ok's catch-up.
            self.record_capture(flag.flag_id, flag.igt_ms, now);
            kept += 1;
        }
        if kept > 0 {
            info!(count = kept, "[RACE] Saved event flags restored");
            self.flush_restored = true;
        }
    }

    // ------------------------------------------------------------------
    // Read accessors (state queries used by the shell and renderer)
    // ------------------------------------------------------------------

    /// Returns true if we're in the countdown period before the race effectively starts.
    pub fn is_countdown_active(&self, now: Instant) -> bool {
        self.race_state
            .countdown_end
            .map(|end| now < end)
            .unwrap_or(false)
    }

    pub fn is_race_running(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == RaceStatus::Running)
            .unwrap_or(false)
    }

    /// IGT for outgoing wire values: the frame value, held through the
    /// transient 0 of a repopulating menu reload. Status updates
    /// deliberately do NOT use this: there, 0 means "not in game, skip the
    /// send".
    fn effective_igt_ms(&self) -> u32 {
        self.held_igt_ms(self.frame_snapshot.igt_ms).unwrap_or(0)
    }

    /// An IGT reading, falling back to the last good observation when it is
    /// zero or missing: the game reads 0, then nothing, while a menu reload
    /// repopulates GameDataMan, and its clock is stopped meanwhile. `None`
    /// until a first good observation since the race start.
    pub fn held_igt_ms(&self, reading: Option<u32>) -> Option<u32> {
        reading.filter(|&v| v > 0).or(self.last_good_igt)
    }

    /// The local IGT the overlay shows, given the game's reading: held
    /// (`held_igt_ms`) while the local runner plays; otherwise the reading,
    /// a zero one counting as none (a runner not yet playing may still be on
    /// another save, whose IGT is no race clock to hold).
    pub fn display_igt_ms(&self, reading: Option<u32>) -> Option<u32> {
        if self
            .my_participant()
            .is_some_and(|p| p.status == ParticipantStatus::Playing)
        {
            self.held_igt_ms(reading)
        } else {
            reading.filter(|&v| v > 0)
        }
    }

    /// The held, freeze-adjusted IGT of the current frame: the game time the
    /// LiveSplit driver pushes.
    pub fn live_igt_ms(&self) -> Option<u32> {
        self.held_igt_ms(self.frame_snapshot.igt_ms)
    }

    /// Configured quit-out penalty, 0 when no race is known (nothing to
    /// penalize outside a race anyway).
    fn quit_out_penalty_ms(&self) -> u32 {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.quit_out_penalty_ms)
            .unwrap_or(0)
    }

    /// Whether the blackscreen IGT freeze may fire. Mirrors the quit-out
    /// penalty gate (mid-run, not finished, not during countdown) plus
    /// wrong-save: never write the timer of a save that is not the race
    /// save.
    fn freeze_gate_open(&self, now: Instant) -> bool {
        self.is_race_running()
            && !self.am_i_finished()
            && !self.is_countdown_active(now)
            && !self.wrong_save
    }

    /// The run is live for LiveSplit: running past the countdown, the local
    /// runner neither finished nor out, on the run's save.
    fn run_live(&self, now: Instant) -> bool {
        self.freeze_gate_open(now) && !self.am_i_abandoned()
    }

    /// Whether the debug-flag read may run: racing for real (not a practice
    /// session, not abandoned), after the countdown, before the local
    /// finish, on a save the server accepts (no local wrong save, no
    /// blocking server condition). Outside it the server ignores the reports
    /// anyway.
    fn debug_flags_gate_open(&self, now: Instant) -> bool {
        (!self.training || self.is_ranked())
            && !self.am_i_abandoned()
            && self.freeze_gate_open(now)
            && self.get_blocking_condition(now).is_none()
    }

    /// Ranked run (Speedrun or Set Seed): a solo session of this kind reads
    /// debug flags like a race; a practice session never does.
    fn is_ranked(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.ranked)
            .unwrap_or(false)
    }

    fn is_deathless(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.deathless)
            .unwrap_or(false)
    }

    pub fn is_race_setup(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.status == RaceStatus::Setup)
            .unwrap_or(false)
    }

    /// Check if the local player has finished the race.
    /// Once finished, the mod should stop sending status_update and event_flag
    /// to preserve the frozen IGT at finish time.
    pub fn am_i_finished(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == ParticipantStatus::Finished)
            .unwrap_or(false)
    }

    /// Whether the local player is out of the race (abandoned or
    /// disqualified); mirrors `am_i_finished`.
    pub fn am_i_abandoned(&self) -> bool {
        self.my_participant()
            .map(|p| p.status.is_out())
            .unwrap_or(false)
            // A relay member out while its team plays on.
            || self.relay_me().is_some_and(|m| m.status.is_out())
    }

    /// Whether the race staff disqualified the local player.
    pub fn am_i_disqualified(&self) -> bool {
        self.my_participant()
            .map(|p| p.status == ParticipantStatus::Disqualified)
            .unwrap_or(false)
    }

    /// The relay team and role the server last named; `None` on a race
    /// without relay.
    pub fn relay(&self) -> Option<&RelayInfo> {
        self.relay.as_ref()
    }

    /// What this process last wrote to the relay lock flag; `None` before any
    /// write.
    pub fn relay_locked(&self) -> Option<bool> {
        self.relay_lock
    }

    /// The runner's relay role: the cached one the server named. It may be
    /// `Some(RelayRole::Unknown)`: callers match `Holder` and `Waiting`
    /// explicitly, never `!= Waiting` or `!= Holder`.
    pub fn relay_role(&self) -> Option<RelayRole> {
        self.relay.as_ref().map(|r| r.role)
    }

    /// The runner's own entry in its team. Its `status`, `zones` and
    /// `validated` are read; its `ready` and `online` never are (the
    /// `auth_ok` echo of them is not authoritative about the runner).
    pub fn relay_me(&self) -> Option<&RelayMember> {
        self.relay.as_ref()?.members.get(self.relay_member?)
    }

    /// Id of the runner's leaderboard row: the team's on a relay race (rows
    /// are teams there), the participant's on any other.
    pub fn my_row_id(&self) -> Option<&str> {
        match &self.relay {
            Some(relay) => Some(relay.team_id.as_str()),
            None => self.my_participant_id.as_deref(),
        }
    }

    /// The runner's relay is over for it: its team finished, abandoned or
    /// was disqualified, or it is out itself while the team plays on. An
    /// unknown status is no decision. `false` without relay.
    pub fn relay_over(&self) -> bool {
        let Some(relay) = &self.relay else {
            return false;
        };
        matches!(
            relay.team_status,
            ParticipantStatus::Finished
                | ParticipantStatus::Abandoned
                | ParticipantStatus::Disqualified
        ) || self.relay_me().is_some_and(|m| m.status.is_out())
    }

    /// The relay is actually being played, so locks and takes apply: the
    /// race runs (countdown included), the team status is `ready` or
    /// `playing` (a setup reads `registered` for everyone, the first runner
    /// included) and the runner is not out. `false` without relay.
    pub fn relay_live(&self) -> bool {
        self.relay.as_ref().is_some_and(|relay| {
            matches!(
                relay.team_status,
                ParticipantStatus::Ready | ParticipantStatus::Playing
            )
        }) && self.is_race_running()
            && !self.relay_over()
    }

    /// The runner holds the baton of a relay being played: the only state in
    /// which its state is asked for or sent. An unknown role is no holder.
    fn relay_holder_live(&self) -> bool {
        self.relay_role() == Some(RelayRole::Holder) && self.relay_live()
    }

    /// The socket is down: what was waiting on it is stale. A release the
    /// server will have cancelled is forgotten (a reconnection does not
    /// repeat it), a capture in flight will answer for nothing, and a
    /// checkpoint not yet asked is dropped (the next zone sends the latest).
    fn relay_link_lost(&mut self) {
        self.relay_release = None;
        self.relay_checkpoint_due = false;
        if let Some(capture) = self.relay_capture.as_mut() {
            capture.link_lost = true;
        }
    }

    /// Replace the relay info whole. A role turning `Waiting` drops the zone
    /// just left (a waiting runner is not in the world its team is playing:
    /// its exits must not stay on the panel); an unknown role changes
    /// nothing.
    fn set_relay(&mut self, relay: Option<RelayInfo>) {
        let turns_waiting = relay.as_ref().is_some_and(|r| r.role == RelayRole::Waiting)
            && self.relay_role() != Some(RelayRole::Waiting);
        // `my_participant_id` is set before the relay info, by the same
        // `auth_ok`, so the index is right for the members it indexes.
        self.relay_member = relay.as_ref().and_then(|r| {
            let me = self.my_participant_id.as_deref()?;
            r.members.iter().position(|m| m.participant_id == me)
        });
        let capped = relay
            .as_ref()
            .is_some_and(|r| r.role == RelayRole::Holder && r.gates_locked);
        self.relay_cap_due = capped && (self.relay_cap_due || !self.relay_capped);
        self.relay_capped = capped;
        if relay.is_none() {
            self.relay_release = None;
            self.relay_checkpoint_due = false;
            self.relay_passed = None;
        }
        self.relay = relay;
        if turns_waiting
            && (self.race_state.current_zone.is_some() || self.pending_zone_update.is_some())
        {
            self.race_state.current_zone = None;
            self.pending_zone_update = None;
            self.pending_zone_received_at = None;
            self.zone_stall_warned = false;
            self.zone_version = self.zone_version.wrapping_add(1);
        }
    }

    pub fn my_participant(&self) -> Option<&ParticipantInfo> {
        let idx = self.my_participant_index?;
        self.race_state.participants.get(idx)
    }

    /// In-game seconds the local runner has left before the race's IGT
    /// cutoff, given their IGT; negative once past it. `None` when the race
    /// has no cutoff or the local runner is not playing (a finished run's
    /// frozen IGT has nothing left to count).
    pub fn igt_cutoff_seconds_left(&self, igt_ms: u32) -> Option<i64> {
        let cutoff = self.race_state.race.as_ref()?.igt_cutoff_ms?;
        if self.my_participant()?.status != ParticipantStatus::Playing {
            return None;
        }
        Some((i64::from(cutoff) - i64::from(igt_ms)) / 1000)
    }

    /// Get current status message if still valid (within 3 seconds).
    pub fn get_status(&self, now: Instant) -> Option<&str> {
        self.status_message.as_ref().and_then(|(msg, time)| {
            if now.duration_since(*time) < Duration::from_secs(3) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    /// The race has items on (use flag reads, inventory reports).
    pub fn race_items_on(&self) -> bool {
        self.race_state
            .race
            .as_ref()
            .map(|r| r.race_items)
            .unwrap_or(false)
    }

    /// The seed catalog's entry for a race item key.
    fn catalog_item(&self, item: &str) -> Option<&RaceItemEntry> {
        self.race_state
            .seed
            .as_ref()?
            .race_item_catalog
            .items
            .get(item)
    }

    /// The seed catalog's entry for a race goods key.
    fn catalog_goods(&self, goods: &str) -> Option<&RaceItemGoods> {
        self.race_state
            .seed
            .as_ref()?
            .race_item_catalog
            .goods
            .get(goods)
    }

    /// A catalog item with the goods it is held as.
    fn item_and_goods(&self, item: &str) -> Option<(&RaceItemEntry, &RaceItemGoods)> {
        let entry = self.catalog_item(item)?;
        Some((entry, self.catalog_goods(&entry.goods)?))
    }

    /// Whether the catalog item `item` is held as the goods `goods`.
    fn item_held_as(&self, item: &str, goods: &str) -> bool {
        self.catalog_item(item)
            .is_some_and(|entry| entry.goods == goods)
    }

    /// Whether the catalog item `item` is held as a goods whose use raises
    /// `flag_id`.
    fn item_used_by(&self, item: &str, flag_id: u32) -> bool {
        self.item_and_goods(item)
            .is_some_and(|(_, goods)| goods.use_flag == Some(flag_id))
    }

    /// The held row of a catalog item: its key, icon and name.
    fn held_row(&self, item: &str) -> Option<FeedHeld> {
        let entry = self.catalog_item(item)?;
        Some(FeedHeld {
            key: item.to_string(),
            icon: entry.icon.clone(),
            text: entry.name.clone(),
        })
    }

    /// The race goods keys an inventory read found: the held item's row
    /// shows while its goods is among them, none otherwise.
    pub fn inventory_read(&mut self, present_goods: &[String]) {
        let row = self
            .held_item
            .as_deref()
            .filter(|item| {
                self.catalog_item(item)
                    .is_some_and(|entry| present_goods.contains(&entry.goods))
            })
            .and_then(|item| self.held_row(item));
        self.item_feed.set_held(row);
    }

    /// The memory state last handed to the shell (`ApplyMemoryState`), the
    /// one the game should hold: the shell compares it with what it wrote,
    /// to write again a state whose batch it lost.
    pub fn memory_state_sent(&self) -> MemoryState {
        self.memory_written
    }

    /// Row of the race item held, if any, while the run is live: an item
    /// left unspent at the finish or when out stops showing.
    pub fn item_held(&self) -> Option<&FeedHeld> {
        let live = self.is_race_running() && !self.am_i_finished() && !self.am_i_abandoned();
        self.item_feed.held().filter(|_| live)
    }

    /// Race item banner on screen, if any (as of the last tick).
    pub fn item_banner(&self) -> Option<&FeedBanner> {
        self.item_feed.banner()
    }

    /// Opacity of that banner at `now` (its fade in and out).
    pub fn item_banner_alpha(&self, now: Instant) -> f32 {
        self.item_feed.banner_alpha(now)
    }

    /// Race item reminder rows still running at `now`, with their time
    /// left on the play clock (`None` for an ink waiting for a zone).
    pub fn item_reminders(
        &self,
        now: Instant,
    ) -> impl Iterator<Item = (&FeedRow, Option<Duration>)> {
        self.item_feed.reminders(self.play_clock.at(now))
    }

    /// An ink effect hides the exit destinations at `now`.
    pub fn ink_active(&self, now: Instant) -> bool {
        self.item_feed.ink_active(self.play_clock.at(now))
    }

    /// Coded blocking condition (red top banner) while fresh.
    pub fn get_blocking_condition(&self, now: Instant) -> Option<&ServerCondition> {
        self.server_condition
            .as_ref()
            .filter(|c| c.kind.is_blocking())
            .filter(|c| now.duration_since(c.last_seen) < SERVER_CONDITION_TTL)
    }

    /// Cheat banner: a watched debug flag is on right now. The other red
    /// banners (permanent server error, coded blocking condition, local
    /// wrong save) take precedence.
    pub fn cheat_warning_active(&self, now: Instant) -> bool {
        self.debug_flags_last.is_some_and(|mask| mask != 0)
            && self.permanent_error.is_none()
            && self.get_blocking_condition(now).is_none()
            && !self.wrong_save
    }

    /// Calm amber waiting line: locally derived when the machine knows
    /// the race has not started, otherwise a fresh waiting condition from
    /// the server. The countdown code stays hidden while the local
    /// countdown UI is active.
    pub fn get_waiting_line(&self, now: Instant) -> Option<&str> {
        if self.is_race_setup() {
            // Only while actually in the world: the reminder is about the
            // loaded game, so it must not cover the title screen or
            // loading screens (the same readable-position signal the
            // loading-exit path keys on).
            return self
                .frame_snapshot
                .position_readable
                .then_some("Race has not started yet");
        }
        self.server_condition
            .as_ref()
            .filter(|c| !c.kind.is_blocking())
            .filter(|c| now.duration_since(c.last_seen) < SERVER_CONDITION_TTL)
            .filter(|c| c.kind != ConditionKind::Countdown || !self.is_countdown_active(now))
            .map(|c| c.message.as_str())
    }

    /// Get the update-available notice if still within its 10s display window.
    pub fn get_update_notice(&self, now: Instant) -> Option<&str> {
        self.update_notice.as_ref().and_then(|(msg, time)| {
            if now.duration_since(*time) < Duration::from_secs(10) {
                Some(msg.as_str())
            } else {
                None
            }
        })
    }

    /// Set a status message that will be displayed temporarily (3 seconds).
    pub fn set_status(&mut self, message: String, now: Instant) {
        self.status_message = Some((message, now));
    }

    fn refresh_my_participant_index(&mut self) {
        self.my_participant_index = self
            .my_row_id()
            .and_then(|id| self.race_state.participants.iter().position(|p| p.id == id));
    }

    fn bump_leaderboard_version(&mut self) {
        self.leaderboard_version = self.leaderboard_version.wrapping_add(1);
    }
}

impl RaceMachine {
    /// Handle one message from the WS worker. Pure: mutates machine state and
    /// returns the side effects for the shell to execute, in order.
    pub fn handle_message(&mut self, msg: MachineMessage, now: Instant) -> Vec<Effect> {
        let mut effects = self.handle_message_inner(msg, now);
        // An auth_ok names the participant: restored flags may go now.
        self.release_restored_flags(now);
        // After the release, so the depths it records reach LiveSplit now.
        self.emit_run_view(now, &mut effects);
        self.persist_unacked_if_changed(&mut effects);
        effects
    }

    fn handle_message_inner(&mut self, msg: MachineMessage, now: Instant) -> Vec<Effect> {
        let mut effects = Vec::new();
        match msg {
            MachineMessage::StatusChanged(status) => {
                info!(status = ?status, "[WS] Status changed");
                match status {
                    ConnectionStatus::Connected => {
                        self.ready_sent = false; // Reset for reconnection
                        self.relay_ready_sent = None;
                        self.set_status("Server connected".to_string(), now);
                    }
                    ConnectionStatus::Reconnecting => {
                        self.relay_link_lost();
                        self.flag_buffer.park_deferred();
                        self.set_status("Reconnecting to server...".to_string(), now);
                    }
                    ConnectionStatus::Error => {
                        self.relay_link_lost();
                        // The permanent red banner already shows this
                        // failure; no gold flash on top of it.
                        if self.permanent_error.is_none() {
                            let msg = self
                                .last_auth_error
                                .take()
                                .unwrap_or_else(|| "Server maintenance".to_string());
                            self.set_status(msg, now);
                        }
                    }
                    ConnectionStatus::Disconnected => {
                        self.relay_link_lost();
                        self.set_status("Disconnected".to_string(), now);
                    }
                    ConnectionStatus::Connecting => {
                        // Silent: the dot indicator handles initial connection
                    }
                }
            }
            MachineMessage::AuthOk {
                participant_id,
                mut race,
                seed,
                participants,
                phantom_skin,
                latest_mod_version,
                held_item,
                relay,
            } => {
                info!(race = %race.name, participant_id = %participant_id, participants = participants.len(), "[WS] Auth OK");
                if let Some(ref name) = phantom_skin {
                    info!(skin = %name, "[WS] Equipped phantom skin received");
                }
                // Phantom skin runtime application: the machine resolves the
                // seed catalog and emits the intent; the shell owns the runner
                // thread and its skip-if-already-running guard.
                if let Some(ref name) = phantom_skin {
                    match seed.phantom_skins.get(name) {
                        Some(directive) if !directive.speffects.is_empty() => {
                            effects.push(Effect::StartPhantomSkin {
                                name: name.clone(),
                                speffects: directive.speffects.clone(),
                            });
                        }
                        Some(_) => {
                            warn!(
                                skin = %name,
                                "[PHANTOM_SKIN] Seed catalog has the skin but no SpEffects; nothing to apply"
                            );
                        }
                        None => {
                            let available: Vec<&String> = seed.phantom_skins.keys().collect();
                            warn!(
                                skin = %name,
                                available = ?available,
                                "[PHANTOM_SKIN] Skin not in this seed's catalog (older seed?), feature disabled"
                            );
                        }
                    }
                }
                // Race item effects call into the game: ready that off the
                // render thread now, not at the first effect.
                if race.race_items {
                    effects.push(Effect::PrewarmRaceItems);
                }
                self.last_received_debug = Some(format!(
                    "auth_ok(race={}, {} players)",
                    race.name,
                    participants.len()
                ));
                // Race items queued or shown for another participant are not
                // this one's; a reconnection as the same one keeps them. The
                // next loaded frame writes the memory defaults back.
                if self.my_participant_id.as_deref() != Some(participant_id.as_str()) {
                    self.item_feed.clear();
                    self.timed_effects.clear();
                    self.memory_effects.clear();
                    self.memory_reminders.clear();
                    self.pending_grants.clear();
                    self.spawning_grants.clear();
                    self.retry_grants.clear();
                    self.pending_item_effects.clear();
                    self.handled_grants.clear();
                    self.drop_hunter("another participant", &mut effects);
                }
                self.my_participant_id = Some(participant_id);
                self.relay_ready_sent = None;
                self.set_relay(relay);
                self.my_participant_index = self
                    .my_row_id()
                    .and_then(|id| participants.iter().position(|p| p.id == id));
                self.event_ids = seed.event_ids.clone();
                self.finish_event = seed.finish_event;
                self.boss_flags = seed.boss_flags.clone();
                self.boss_flags.sort_unstable();
                self.boss_flags.dedup();
                self.boss_read_cursor = 0;
                self.item_use_flags = seed
                    .race_item_catalog
                    .goods
                    .values()
                    .filter_map(|goods| goods.use_flag)
                    .collect();
                self.item_use_flags.sort_unstable();
                self.item_use_flags.dedup();
                self.item_inventory_goods = seed
                    .race_item_catalog
                    .goods
                    .iter()
                    .map(|(key, goods)| (key.clone(), goods.goods_id))
                    .collect();
                self.item_inventory_goods.sort_unstable();
                // The server's word on the item held, whichever participant:
                // a restarted process restores its icon and row from it.
                if let Some(ref item) = held_item {
                    info!(item = %item, "[ITEMS] Held item named at auth");
                }
                // A grant still queued that the server no longer holds (its
                // goods spent or taken back while this mod was offline, the
                // `item_remove` lost) must not spawn at the next load; the
                // one it holds unconfirmed comes again right after this.
                let queued = self.pending_grants.len() + self.retry_grants.len();
                self.pending_grants
                    .retain(|g| held_item.as_deref() == Some(g.item.as_str()));
                self.retry_grants
                    .retain(|g| held_item.as_deref() == Some(g.item.as_str()));
                let dropped = queued - self.pending_grants.len() - self.retry_grants.len();
                if dropped > 0 {
                    info!(dropped, "[ITEMS] Queued grants dropped (not held at auth)");
                }
                self.held_item = held_item;
                // Don't clear triggered_flags on reconnect: finish_event and
                // boss kills are one-shot.
                // Regular fog gate flags are no longer tracked in triggered_flags;
                // they're cleared in game memory after capture for re-traversal detection.
                race.reparse_dates();
                self.race_state.race = Some(race);
                self.frozen_igt_ms = None;

                // Detect seed mismatch (stale seed pack after re-roll)
                self.seed_mismatch =
                    crate::core::is_seed_stale(&self.config_seed_id, seed.seed_id.as_deref());
                if self.seed_mismatch {
                    warn!(
                        config = %self.config_seed_id,
                        server = ?seed.seed_id,
                        "Seed mismatch: seed pack is outdated"
                    );
                }

                if let Some(latest) = latest_mod_version {
                    info!(latest = %latest, "[WS] Mod update available");
                    // Formatted once at receipt; rendering reads it by reference.
                    self.update_notice = Some((
                        format!(
                            "Mod update available: v{} (you have v{})",
                            latest,
                            env!("CARGO_PKG_VERSION")
                        ),
                        now,
                    ));
                }

                // Spawn runtime items (gems/AoW) if present in seed; the shell
                // re-checks its items_spawned / thread-liveness guards.
                if !seed.spawn_items.is_empty() {
                    effects.push(Effect::SpawnItems);
                }
                self.race_state.seed = Some(seed);
                self.race_state.participants = participants;
                self.bump_leaderboard_version();

                // The run's arrivals, sized for this seed (those recorded
                // before a reconnect stay), then merged with the local
                // runner's arrivals the server knows: the catch-up after a
                // relaunch.
                let total_layers = self.race_state.seed.as_ref().map_or(0, |s| s.total_layers);
                let len = usize::try_from(total_layers).unwrap_or(0) + 1;
                if self.run_arrivals.len() != len {
                    self.run_arrivals.resize(len, None);
                    self.run_view_changed = true;
                }
                if let Some(igts) = self
                    .my_participant()
                    .and_then(|p| p.layer_entry_igts.clone())
                {
                    for layer in 1..=total_layers {
                        if let Some(igt) = igts.get(&layer).and_then(|&v| u32::try_from(v).ok()) {
                            self.record_arrival(layer, igt);
                        }
                    }
                }
            }
            MachineMessage::AuthError(msg) => {
                self.last_received_debug = Some(format!("auth_error({})", msg));
                error!(message = %msg, "[WS] Auth failed");
                self.last_auth_error = Some(msg);
            }
            MachineMessage::RaceStart(countdown_seconds) => {
                self.last_received_debug = Some(format!("race_start(cd={})", countdown_seconds));
                info!(countdown_seconds, "[WS] Race started!");
                self.race_state.race_started_at = Some(now);
                if countdown_seconds > 0 {
                    self.race_state.countdown_end =
                        Some(now + Duration::from_secs(countdown_seconds as u64));
                } else {
                    self.race_state.countdown_end = None;
                }
                // A real start is a new attempt at the run, a re-run after a
                // race reset included: the voided run's depths go. The
                // race_start a solo server sends after every auth_ok, its
                // run already running, is no start.
                if !self.is_race_running() {
                    self.start_attempt();
                    // A reset keeps the participant, so its auth_ok kept the
                    // race items of the voided run; the server's reset
                    // cleared its side of them.
                    self.drop_waiting_race_items("new start", &mut effects);
                    self.item_feed.clear_timers();
                    self.held_item = None;
                    // A use of the voided run still unacked would be
                    // replayed into this one, where its IGT may pass for a
                    // use of an item granted since.
                    let use_flags = &self.item_use_flags;
                    self.in_flight_event_flags
                        .retain(|_, flag| use_flags.binary_search(&flag.flag_id).is_err());
                }
                // Immediately reflect running status so is_race_running() gates open
                // without waiting for the race_status_change message that follows.
                if let Some(ref mut race) = self.race_state.race {
                    race.status = RaceStatus::Running;
                }
                // A quit-out requested before the start is not a race quit-out.
                self.pending_quit_out = false;
                self.deathless_banner_shown = false;
                self.debug_flags_seen = 0;
                self.debug_flags_last = None;
                // Without this, the IGT-regression arming would fire on the
                // first in-race load after a pre-start quit-out (the reloaded
                // save's IGT sits below the last pre-start observation).
                self.has_been_in_world = false;
                // A wrong-save freeze from before the start is stale: the
                // race begins with a clean slate and fresh references, so a
                // pre-start mistake cannot leave the machine frozen forever
                // (the race save's IGT may sit far below the stale baseline).
                self.wrong_save = false;
                self.last_good_igt = None;
                self.last_good_at = None;
                self.freeze_last_igt = None;
                self.bump_leaderboard_version();
            }
            MachineMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                self.last_received_debug = Some(format!(
                    "leaderboard_update({} players)",
                    participants.len()
                ));
                debug!(count = participants.len(), "[WS] Leaderboard update");
                // Snapshot current_layer before it gets bumped by the new
                // participants list, so the UI keeps the old X/Y and tier
                // until the zone name is revealed.
                if self.pre_reveal_layer.is_none() {
                    if let Some(my_id) = self.my_row_id() {
                        let old_layer = self
                            .race_state
                            .participants
                            .iter()
                            .find(|p| p.id == my_id)
                            .map(|p| p.current_layer);
                        let new_layer = participants
                            .iter()
                            .find(|p| p.id == my_id)
                            .map(|p| p.current_layer);
                        if old_layer != new_layer {
                            self.pre_reveal_layer = old_layer;
                        }
                    }
                }
                self.race_state.participants = participants;
                self.race_state.leader_splits = leader_splits;
                self.refresh_my_participant_index();
                self.bump_leaderboard_version();
            }
            MachineMessage::RaceStatusChange {
                status,
                current_igt,
            } => {
                self.last_received_debug = Some(format!("race_status_change({})", status.as_str()));
                info!(status = %status.as_str(), "[WS] Race status changed");
                // If race ends and we haven't finished, freeze our current game IGT.
                // The mod's local participant igt_ms is stale (only updated via
                // leaderboard_update on events, not on every status_update).
                // `current_igt` is a fresh read injected by the shell.
                if status == RaceStatus::Finished && !self.am_i_finished() {
                    self.frozen_igt_ms = self.display_igt_ms(current_igt);
                    self.frame_snapshot.igt_ms = self.frozen_igt_ms;
                    info!(frozen_igt_ms = ?self.frozen_igt_ms, "[WS] Froze game IGT (race ended, player not finished)");
                }
                if let Some(ref mut race) = self.race_state.race {
                    race.status = status;
                }
                self.bump_leaderboard_version();
            }
            MachineMessage::RaceInfoUpdate(mut race) => {
                self.last_received_debug = Some(format!("race_info_update(name={})", race.name));
                info!(
                    race_ends_at = ?race.race_ends_at,
                    igt_cutoff_ms = ?race.igt_cutoff_ms,
                    status = %race.status.as_str(),
                    "[WS] Race info updated"
                );
                race.reparse_dates();
                // A reroll changes the race's seed_id mid-session; re-check
                // whether the loaded pack went stale (auth_ok is the only other
                // place this is evaluated). Only act when the payload carries a
                // seed_id, so an older server omitting it can't clear the flag.
                if race.seed_id.is_some() {
                    self.seed_mismatch =
                        crate::core::is_seed_stale(&self.config_seed_id, race.seed_id.as_deref());
                    if self.seed_mismatch {
                        warn!(
                            config = %self.config_seed_id,
                            server = ?race.seed_id,
                            "Seed mismatch after reroll: seed pack is outdated"
                        );
                    }
                }
                self.race_state.race = Some(race);
            }
            MachineMessage::PlayerUpdate(player) => {
                // Snapshot current_layer on increase (same rationale as LeaderboardUpdate).
                if self.pre_reveal_layer.is_none() {
                    if let Some(my_id) = self.my_row_id() {
                        if player.id == my_id {
                            if let Some(old_me) = self.my_participant() {
                                if player.current_layer > old_me.current_layer {
                                    self.pre_reveal_layer = Some(old_me.current_layer);
                                }
                            }
                        }
                    }
                }
                if let Some(p) = self
                    .race_state
                    .participants
                    .iter_mut()
                    .find(|p| p.id == player.id)
                {
                    *p = player;
                }
                self.refresh_my_participant_index();
                self.bump_leaderboard_version();
            }
            MachineMessage::ZoneUpdate {
                node_id,
                display_name,
                tier,
                original_tier,
                layer,
                is_first_visit,
                exits,
                unused_exits,
                defeat_flag,
                message_id,
            } => {
                if let Some(mid) = message_id {
                    self.in_flight_zone_queries.remove(&mid);
                }
                self.last_received_debug = Some(format!("zone_update({})", display_name));
                info!(node = %node_id, name = %display_name, first = is_first_visit, "[WS] Zone update (pending reveal)");
                // Last-writer-wins: if two flags fire in rapid succession, only the
                // final destination zone is shown (intermediate corridor zones are skipped).
                self.pending_zone_update = Some(ZoneUpdateData {
                    display_name,
                    tier,
                    original_tier,
                    layer,
                    is_first_visit,
                    exits,
                    unused_exits,
                    defeat_flag,
                });
                self.pending_zone_received_at = Some(now);
                self.zone_stall_warned = false;
            }
            MachineMessage::EventFlagAck { message_id } => {
                if let Some(event) = self.in_flight_event_flags.remove(&message_id) {
                    info!(
                        message_id,
                        flag_id = event.flag_id,
                        "[WS] Event flag acknowledged"
                    );
                } else {
                    warn!(message_id, "[WS] Ack for unknown event flag");
                }
            }
            MachineMessage::RequeueEventFlag {
                flag_id,
                igt_ms,
                message_id,
            } => {
                // Event flag was in the outgoing channel but never transmitted.
                // Remove from in-flight (server never saw it) and add to pending
                // buffer for resend with a fresh message_id.
                self.in_flight_event_flags.remove(&message_id);
                self.flag_buffer.add_pending(flag_id, igt_ms);
                info!(flag_id, message_id, "[WS] Re-queued drained event flag");
            }
            MachineMessage::RequeueZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
                quit_out,
            } => {
                self.in_flight_zone_queries
                    .entry(message_id)
                    .or_insert(BufferedZoneQuery {
                        igt_ms,
                        grace_entity_id,
                        map_id,
                        position,
                        play_region_id,
                        quit_out,
                    });
                info!(message_id, "[WS] Re-queued drained zone query");
            }
            MachineMessage::ZoneQueryAck { message_id } => {
                if self.in_flight_zone_queries.remove(&message_id).is_some() {
                    info!(message_id, "[WS] Zone query acknowledged (no zone_update)");
                    // No zone_update comes for this query (unresolved, as
                    // after some death reloads): an ink not run yet goes by
                    // the current zone, unless a reveal is pending (it
                    // decides).
                    if self.pending_zone_update.is_none() {
                        let start = self.ink_start(self.race_state.current_zone.as_ref());
                        if self.item_feed.decide_ink(start, self.play_clock.at(now)) {
                            log_ink(start, "zone query unresolved");
                        }
                    }
                } else {
                    warn!(message_id, "[WS] Ack for unknown zone query");
                }
            }
            MachineMessage::DeathCounts(counts) => {
                self.last_received_debug = Some(format!("death_counts({} zones)", counts.len()));
                self.race_state.death_counts = counts.clone();
                // Death marker flags: the machine picks flag/value pairs from
                // its seed state; the shell resolves the category page once and
                // writes them, skipping unresolvable flags, exactly as before.
                if let Some(ref seed) = self.race_state.seed {
                    for (node_id, total) in &counts {
                        if let Some(flags) = seed.death_flags.get(node_id) {
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[0],
                                value: *total >= 1,
                            });
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[1],
                                value: *total >= 3,
                            });
                            effects.push(Effect::SetGameFlag {
                                flag_id: flags[2],
                                value: *total >= 5,
                            });
                        }
                    }
                }
            }
            MachineMessage::Error { message, code } => {
                self.last_received_debug = Some(format!("error({})", message));
                warn!(error = %message, code = ?code, "[WS] Error");
                match code.filter(|k| *k != ConditionKind::Unknown) {
                    Some(kind) => {
                        self.server_condition = Some(ServerCondition {
                            kind,
                            message,
                            last_seen: now,
                        });
                    }
                    None => self.set_status(message, now),
                }
            }
            MachineMessage::PermanentError(msg) => {
                self.last_received_debug = Some(format!("permanent_error({})", msg));
                error!(message = %msg, "[WS] Permanent error, stopping reconnection");
                self.permanent_error = Some(msg);
            }
            MachineMessage::ItemGrant {
                grant_id,
                item,
                banner,
            } => {
                self.last_received_debug = Some(format!("item_grant({grant_id}, {item})"));
                // A grant names the item held, a resent one included.
                self.held_item = Some(item.clone());
                // The server sends a grant again at every auth until it
                // hears `item_received`.
                if self.handled_grants.contains(&grant_id) {
                    if self.seed_mismatch {
                        // An outdated pack confirms nothing; the server
                        // sends the grant again at the next auth.
                        info!(grant_id, item = %item, "[ITEMS] Grant already spawned, not acknowledged (seed pack outdated)");
                    } else {
                        info!(grant_id, item = %item, "[ITEMS] Grant already spawned, acknowledged");
                        effects.push(Effect::SendItemReceived { grant_id });
                    }
                } else if self
                    .pending_grants
                    .iter()
                    .chain(&self.spawning_grants)
                    .chain(&self.retry_grants)
                    .any(|g| g.grant_id == grant_id)
                {
                    info!(grant_id, item = %item, "[ITEMS] Grant already waiting for the load");
                } else {
                    // The server only grants to a runner holding nothing: a
                    // grant still queued here is gone on its side (spent,
                    // lost), and its goods must not spawn after this one's.
                    let queued = self.pending_grants.len() + self.retry_grants.len();
                    if queued > 0 {
                        info!(
                            grant_id,
                            queued, "[ITEMS] Queued grants dropped (a newer grant)"
                        );
                        self.pending_grants.clear();
                        self.retry_grants.clear();
                    }
                    match self
                        .item_and_goods(&item)
                        .map(|(entry, goods)| (goods.goods_id, entry.icon_id))
                    {
                        Some((goods_id, icon_id)) => {
                            info!(grant_id, item = %item, goods_id, icon_id, "[ITEMS] Grant received");
                            self.pending_grants.push(PendingGrant {
                                grant_id,
                                item,
                                goods_id,
                                icon_id,
                                banner: FeedBanner::from_wire(&banner, FeedTone::Gain),
                            });
                        }
                        None => {
                            warn!(grant_id, item = %item, "[ITEMS] Grant of an item outside the seed catalog, dropped");
                        }
                    }
                }
            }
            MachineMessage::ItemEffect {
                item,
                effect,
                banner,
                reminder,
            } => {
                self.last_received_debug = Some(format!("item_effect({item})"));
                // A timed effect keeps its duration as the time left of its
                // application (see `flush_race_items`).
                let action = match effect {
                    ItemEffectPayload::Speffect {
                        speffect_id,
                        duration_ms,
                    } => Some(ItemAction::Shell(Effect::ApplySpEffect {
                        speffect_id,
                        left_ms: duration_ms,
                    })),
                    ItemEffectPayload::Damage {
                        base_pct,
                        floor_pct,
                        tail_pct,
                    } => Some(ItemAction::Shell(Effect::ApplyItemDamage {
                        base_pct,
                        floor_pct,
                        tail_pct,
                    })),
                    ItemEffectPayload::Ink { duration_ms } => Some(ItemAction::Ink(
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::EquipLoad {
                        speffect_id,
                        load_pct,
                        duration_ms,
                    } => Some(ItemAction::Shell(Effect::ApplyEquipLoad {
                        speffect_id,
                        load_pct,
                        left_ms: duration_ms,
                    })),
                    ItemEffectPayload::Vanish { duration_ms } => Some(ItemAction::Memory(
                        MemoryEffect::Vanish,
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::UnseenFoes { duration_ms } => Some(ItemAction::Memory(
                        MemoryEffect::UnseenFoes,
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::SlowMo {
                        speed_pct,
                        duration_ms,
                    } => Some(ItemAction::Memory(
                        MemoryEffect::SlowMo {
                            speed: f32::from(speed_pct) / 100.0,
                        },
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::Scale {
                        scale_pct,
                        duration_ms,
                    } => Some(ItemAction::Memory(
                        MemoryEffect::Scale {
                            scale: f32::from(scale_pct) / 100.0,
                        },
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::Lightning {
                        speffect_id,
                        scale_pct,
                        duration_ms,
                    } => Some(ItemAction::Lightning {
                        speffect_id,
                        scale: f32::from(scale_pct) / 100.0,
                        duration: Duration::from_millis(u64::from(duration_ms)),
                    }),
                    // A camera this build does not know has nothing to write.
                    ItemEffectPayload::Camera {
                        variant: CameraVariant::Unknown,
                        ..
                    }
                    | ItemEffectPayload::Unknown => None,
                    ItemEffectPayload::Camera {
                        variant,
                        duration_ms,
                    } => Some(ItemAction::Memory(
                        MemoryEffect::Camera(variant),
                        Duration::from_millis(u64::from(duration_ms)),
                    )),
                    ItemEffectPayload::StealTalisman {
                        talismans,
                        roll,
                        report_id,
                    } => Some(ItemAction::Shell(Effect::StealTalisman {
                        talismans,
                        roll,
                        report_id,
                    })),
                    ItemEffectPayload::Talisman { talisman_id } => {
                        Some(ItemAction::Shell(Effect::SpawnTalisman { talisman_id }))
                    }
                    ItemEffectPayload::JunkWeapon { weapon_id } => {
                        Some(ItemAction::Shell(Effect::EquipJunkWeapon { weapon_id }))
                    }
                    ItemEffectPayload::Hunter {
                        chr_id,
                        npc_param_id,
                        think_id,
                        duration_ms,
                        report_id,
                    } => Some(ItemAction::Hunter(HunterSpec {
                        chr_id,
                        npc_param_id,
                        think_id,
                        duration: Duration::from_millis(u64::from(duration_ms)),
                        report_id,
                        notice: HunterNotice::default(),
                    })),
                };
                match action {
                    Some(action) => {
                        info!(item = %item, ?action, "[ITEMS] Effect received");
                        let banner =
                            banner.map(|banner| FeedBanner::from_wire(&banner, FeedTone::Malus));
                        // The reminder's icon: the banner's, else the item's.
                        let icon = match (&banner, self.catalog_item(&item)) {
                            (Some(banner), _) => banner.icon.clone(),
                            (None, Some(entry)) => entry.icon.clone(),
                            (None, None) => item.clone(),
                        };
                        self.pending_item_effects.push(PendingItemEffect {
                            action,
                            banner,
                            icon,
                            reminder,
                        });
                    }
                    None => {
                        warn!(item = %item, "[ITEMS] Effect of an unknown kind or variant, dropped");
                    }
                }
            }
            MachineMessage::ItemResult {
                item,
                banner,
                reminder,
            } => {
                self.last_received_debug = Some(format!("item_result({item})"));
                info!(item = %item, "[ITEMS] Result received");
                // The server resolves a use only after spending the item
                // held: a value left by an auth_ok or a resent grant that
                // raced the use capture goes too. A later grant sets it again.
                self.held_item = None;
                // The sender's own outcome: shown at once, no game access.
                let banner = FeedBanner::from_wire(&banner, FeedTone::Gain);
                if let Some(reminder) = reminder {
                    self.item_feed.add_reminder(
                        banner.icon.clone(),
                        reminder.text,
                        FeedTone::Gain,
                        Duration::from_millis(u64::from(reminder.duration_ms)),
                        self.play_clock.at(now),
                    );
                }
                self.item_feed.push_banner(banner, now);
            }
            MachineMessage::RelayUpdate(relay) => {
                self.last_received_debug = Some(format!("relay_update({:?})", relay.role));
                debug!(role = ?relay.role, team_status = ?relay.team_status, "[RELAY] Update");
                let was_waiting = self.relay_role() == Some(RelayRole::Waiting);
                let turns_waiting = relay.role == RelayRole::Waiting && !was_waiting;
                self.set_relay(Some(relay));
                // The server's flip: only now is the baton passed. An answer
                // older than the server's own wait for it was another
                // handoff's (a takeover reads the same).
                if turns_waiting {
                    if let Some((to_name, answered_at)) = self.relay_passed.take() {
                        if now.saturating_duration_since(answered_at) < relay::RELEASE_WINDOW
                            && !self.relay_over()
                        {
                            self.item_feed.push_banner(
                                FeedBanner {
                                    icon: String::new(),
                                    title: format!("BATON PASSED TO {}", to_name.to_uppercase()),
                                    line: String::new(),
                                    detail: String::new(),
                                    tone: FeedTone::Gain,
                                },
                                now,
                            );
                        }
                    }
                }
            }
            MachineMessage::RelayRelease {
                handoff_id,
                to_name,
            } => {
                self.last_received_debug = Some(format!("relay_release({handoff_id})"));
                if !self.relay_holder_live() {
                    warn!(
                        role = ?self.relay_role(),
                        "[RELAY] Release ignored: not the holder of a live relay"
                    );
                } else if self
                    .relay_release
                    .as_ref()
                    .is_some_and(|pending| pending.handoff_id == handoff_id)
                {
                    debug!(handoff_id = %handoff_id, "[RELAY] Release repeated");
                } else {
                    info!(handoff_id = %handoff_id, to = %to_name, "[RELAY] Release received");
                    self.relay_passed = None;
                    self.relay_release = Some(PendingRelease {
                        handoff_id,
                        to_name,
                        deadline: now + relay::RELEASE_CAPTURE_TIMEOUT,
                    });
                }
            }
            MachineMessage::RelayRefused { code, message } => {
                self.last_received_debug = Some(format!("relay_refused({code})"));
                warn!(code = %code, message = %message, "[RELAY] Request refused");
                self.set_status(message, now);
            }
            MachineMessage::ItemNotice { banner } => {
                self.last_received_debug = Some("item_notice".to_string());
                info!(title = %banner.title, "[ITEMS] Notice received");
                // Nothing to apply: shown at once, as a Shield's block.
                self.item_feed
                    .push_banner(FeedBanner::from_wire(&banner, FeedTone::Gain), now);
            }
            MachineMessage::ItemRemove { goods, banner } => {
                self.last_received_debug = Some(format!("item_remove({goods})"));
                match self
                    .catalog_goods(&goods)
                    .map(|entry| (entry.remove_flag, entry.goods_id))
                {
                    Some((remove_flag, goods_id)) => {
                        // The server holds no item of that goods any more:
                        // a grant of it still queued would spawn a copy at
                        // the next load, after the removal.
                        let queued = self.pending_grants.len() + self.retry_grants.len();
                        self.pending_grants.retain(|g| g.goods_id != goods_id);
                        self.retry_grants.retain(|g| g.goods_id != goods_id);
                        let dropped = queued - self.pending_grants.len() - self.retry_grants.len();
                        if dropped > 0 {
                            info!(goods = %goods, dropped, "[ITEMS] Queued grants dropped (goods removed)");
                        }
                        if self.wrong_save {
                            // No flag writes into a foreign save: the race
                            // save's next inventory report gets the removal
                            // sent again.
                            info!(goods = %goods, remove_flag, "[ITEMS] Removal skipped (wrong save)");
                        } else {
                            // Only raised: the game's event removes the
                            // goods and clears it.
                            info!(goods = %goods, remove_flag, "[ITEMS] Removal flag raised");
                            effects.push(Effect::SetGameFlag {
                                flag_id: remove_flag,
                                value: true,
                            });
                        }
                        // The item held as that goods goes with it; one held
                        // as another goods stays.
                        if self
                            .held_item
                            .as_deref()
                            .is_some_and(|item| self.item_held_as(item, &goods))
                        {
                            self.held_item = None;
                        }
                        if self
                            .item_feed
                            .held()
                            .is_some_and(|row| self.item_held_as(&row.key, &goods))
                        {
                            self.item_feed.set_held(None);
                        }
                        if let Some(banner) = banner {
                            self.item_feed
                                .push_banner(FeedBanner::from_wire(&banner, FeedTone::Gain), now);
                        }
                    }
                    None => {
                        warn!(goods = %goods, "[ITEMS] Removal of a goods outside the seed catalog, dropped");
                    }
                }
            }
        }
        effects
    }
}

/// Defensive timeout for the zone reveal, anchored on zone_update receipt.
/// On frozen-clock event seeds (weather plugin FreezeTime) the loading byte
/// never clears and the reveal falls back to this bound; loads usually last
/// at least this long, so the degraded reveal lands near the loading exit.
const ZONE_REVEAL_TIMEOUT: Duration = Duration::from_secs(5);

/// SoulSplitter's freeze guard: a fade frame only re-writes the frozen IGT
/// while the game-side creep stays below this; a bigger jump is a
/// legitimate discontinuity (save load) and re-seeds the baseline instead.
const BLACKSCREEN_FREEZE_MAX_STEP_MS: u32 = 1_000;

/// A same-save reload always comes back BELOW the last observation (the
/// on-disk save lags); a forward jump across an unload beyond this slack
/// means another, further-along save file.
const WRONG_SAVE_FORWARD_SLACK_MS: u32 = 10_000;
/// Recovery window slack: the race save is back when a reload lands in
/// `[last_good - SAVE_RELOAD_IGT_DROP_MS, last_good + elapsed + this]`.
const WRONG_SAVE_RECOVERY_SLACK_MS: u32 = 10_000;

/// Diagnostic only: how long a zone update may stay pending before a
/// one-shot warn! is logged. Both reveal paths require a readable position,
/// so this log is the only trace left when position readability breaks or
/// flickers and reveals silently stop firing.
const ZONE_REVEAL_STALL_WARN: Duration = Duration::from_secs(30);

/// While a memory race item effect is live on a loaded race save, its state
/// is written again this often (wall time), so a field the game reset or a
/// write that failed comes back shortly.
const MEMORY_REFRESH_INTERVAL: Duration = Duration::from_millis(250);

/// While the foes are hidden, the write walks the characters around this
/// often, hiding those loaded since. A walk visits every loaded character:
/// it is the costly part of the write.
const FOES_WALK_INTERVAL: Duration = Duration::from_secs(1);

/// A server condition displays while its last receipt is younger than
/// this; the server re-sends ~1/s while the condition holds, so display
/// drops by itself shortly after resolution.
const SERVER_CONDITION_TTL: Duration = Duration::from_secs(3);

/// Log what the zone that decides made of an ink not run yet, and why
/// (`by`: the hit, a reveal, a kill...).
fn log_ink(start: InkStart, by: &'static str) {
    match start {
        InkStart::Run => info!(by, "[ITEMS] Ink started"),
        InkStart::Hold => info!(by, "[ITEMS] Ink held, exits hidden until the boss dies"),
        InkStart::Wait => info!(by, "[ITEMS] Ink waits for a zone with unused exits"),
    }
}

/// Boss defeat flags read per flag scan, at most. They sit outside the
/// category page the scan caches for `event_ids`, so each read is a full
/// category lookup (a tree walk of several cross-process memory reads): the
/// scans rotate through the unreported flags instead of reading them all,
/// and each of n is read every ceil(n / this) scans.
const BOSS_FLAG_READS_PER_POLL: usize = 8;

impl RaceMachine {
    /// What the shell should read from the game this frame.
    pub fn pre_tick(&self, now: Instant, show_ui: bool, connected: bool) -> FrameNeeds {
        let live = show_ui || connected;
        FrameNeeds {
            // IGT also needed when a race is set up so save-reload detection
            // and event-flag polling stay correct with UI hidden and WS down.
            igt: live || !self.event_ids.is_empty(),
            deaths: live,
            loading: self.pending_zone_update.is_some(),
            blackscreen: self.freeze_gate_open(now) || self.pending_zone_update.is_some(),
            poll_flags: !self.wrong_save
                && !self.event_ids.is_empty()
                && now.duration_since(self.last_flag_poll) >= Duration::from_millis(100),
            debug_flags: self.debug_flags_gate_open(now)
                && now.duration_since(self.last_debug_flags_poll) >= Duration::from_millis(100),
            hp: self.relay_wants_hp(now),
        }
    }

    /// Whether the shell must read the event flags this frame: 10Hz poll
    /// cadence, loading-screen exit scan, or the reconnect safety-net rescan.
    pub fn wants_flag_reads(
        &self,
        needs: FrameNeeds,
        position_readable: bool,
        connected: bool,
    ) -> bool {
        if self.wrong_save || self.event_ids.is_empty() {
            return false;
        }
        needs.poll_flags
            || (position_readable && !self.was_position_readable)
            || (connected && !self.ready_sent)
    }

    /// The boss defeat flags the shell reads after `event_ids`: while the run
    /// is live (race running, runner neither finished nor out, the only time
    /// `capture_boss_kill` acts), at most `BOSS_FLAG_READS_PER_POLL` of those
    /// not reported yet, from `boss_read_cursor` on and wrapping around, so
    /// successive scans rotate through them. A reported kill takes no slot,
    /// and is read again only once a save reload clears `triggered_flags`.
    pub fn boss_flags_to_read(&self) -> impl Iterator<Item = u32> + '_ {
        let live = self.is_race_running() && !self.am_i_finished() && !self.am_i_abandoned();
        let flags: &[u32] = if live { &self.boss_flags } else { &[] };
        let (before, from_cursor) = flags.split_at(self.boss_read_cursor.min(flags.len()));
        from_cursor
            .iter()
            .chain(before)
            .copied()
            .filter(|flag_id| !self.triggered_flags.contains(flag_id))
            .take(BOSS_FLAG_READS_PER_POLL)
    }

    /// The race item use flags the shell reads after the boss window: every
    /// one of them on every scan, while the run is live (as for the boss
    /// flags) in a race with items.
    pub fn item_use_flags_to_read(&self) -> impl Iterator<Item = u32> + '_ {
        let live = self.race_items_on()
            && self.is_race_running()
            && !self.am_i_finished()
            && !self.am_i_abandoned();
        let flags: &[u32] = if live { &self.item_use_flags } else { &[] };
        flags.iter().copied()
    }

    /// The shell's outcome for a `SpawnRaceItem`: `spawned` when the goods
    /// are in the inventory, freshly given or already there (the shell then
    /// answers `item_received`). Only then is the grant handled, so one the
    /// server sends again is only acknowledged, and its banner shows. A
    /// failed spawn (nothing injected, inventory unreadable) waits for the
    /// next game load or reconnection to be tried again.
    pub fn grant_spawn_result(&mut self, grant_id: u64, spawned: bool, now: Instant) {
        let Some(index) = self
            .spawning_grants
            .iter()
            .position(|g| g.grant_id == grant_id)
        else {
            warn!(
                grant_id,
                "[ITEMS] Spawn outcome of a grant not being spawned"
            );
            return;
        };
        let grant = self.spawning_grants.remove(index);
        if spawned {
            info!(grant_id, "[ITEMS] Grant spawned");
            self.handled_grants.insert(grant_id);
            // A runner holds one item at a time: the new one is the row.
            let held = self.held_row(&grant.item);
            self.item_feed.set_held(held);
            self.item_feed.push_banner(grant.banner, now);
        } else {
            info!(
                grant_id,
                "[ITEMS] Grant spawn failed, retried at the next load or reconnection"
            );
            self.retry_grants.push(grant);
        }
    }

    /// The shell's outcome for a `StealTalisman`: the talisman it took, or
    /// `None` (nothing worn the table knows, slots unreadable). Returns the
    /// `item_report` to send: landed with the talisman, or not landed.
    pub fn talisman_steal_result(&self, report_id: u64, stolen: Option<u32>) -> Vec<Effect> {
        match stolen {
            Some(talisman_id) => info!(report_id, talisman_id, "[ITEMS] Talisman stolen"),
            None => info!(report_id, "[ITEMS] Nothing to steal"),
        }
        vec![Effect::SendItemReport {
            report_id,
            landed: stolen.is_some(),
            talisman_id: stolen,
        }]
    }

    /// The shell's outcome for a `RequestHunter`: `started` when the spawn
    /// was handed to the game. A refused one counts as a miss at once.
    pub fn hunter_request_result(&mut self, started: bool, now: Instant) {
        if !started {
            info!("[ITEMS] Hunter spawn refused, counted as a miss");
        }
        self.hunter.request_result(started, now);
    }

    /// The shell's outcome for a `FindHunter`: `found` when a live character
    /// of the Hunter's row is around. One that hunted and is gone (a load or
    /// a kill removed him) ends the hunt there, his reminder row with it.
    pub fn hunter_seen(&mut self, found: bool, now: Instant) {
        let hunting = self.hunter.is_hunting();
        self.hunter.seen(found, now, self.play_clock.at(now));
        if hunting && !self.hunter.is_hunting() {
            info!("[ITEMS] Hunter gone (a load or a kill removed him), the hunt is over");
            self.drop_hunter_row();
        }
    }

    /// Remove the reminder row of the Hunter found last, if any is left.
    fn drop_hunter_row(&mut self) {
        if let Some(text) = self.hunter_row.take() {
            self.item_feed.remove_reminder(&text);
        }
    }

    /// Moves the boss read rotation past the window `boss_flags_to_read`
    /// names, so the next scan reads the following flags. Called on a frame
    /// whose flags were read, before anything changes that window: past it
    /// whether its flags were readable or not, so an unreadable flag waits
    /// for its next turn instead of holding the rotation. An empty window
    /// (run not live, every flag reported) leaves it where it is.
    fn advance_boss_reads(&mut self) {
        let last = self
            .boss_flags_to_read()
            .last()
            .and_then(|flag_id| self.boss_flags.binary_search(&flag_id).ok());
        if let Some(index) = last {
            self.boss_read_cursor = (index + 1) % self.boss_flags.len();
        }
    }

    /// Whether a status_update may fire this frame (gates the weapon read).
    pub fn wants_status_update(&self, now: Instant, igt_ms: u32) -> bool {
        now.duration_since(self.last_status_update) >= Duration::from_secs(1)
            && igt_ms > 0
            && !self.wrong_save
            && self.is_race_running()
            && !self.am_i_finished()
            && !self.is_countdown_active(now)
    }

    /// One frame of the race lifecycle. Consumes the shell-gathered inputs
    /// and returns the effects to execute, in order. Mirrors the pre-machine
    /// `RaceTracker::update()` body exactly (minus shell concerns).
    pub fn tick(&mut self, input: TickInput, now: Instant) -> Vec<Effect> {
        let mut effects = self.tick_frame(input, now);
        self.emit_run_view(now, &mut effects);
        self.persist_unacked_if_changed(&mut effects);
        effects
    }

    /// `tick` before the run view and the unacknowledged-flags save, which
    /// follow every path a frame takes.
    fn tick_frame(&mut self, input: TickInput, now: Instant) -> Vec<Effect> {
        let mut effects = Vec::new();
        // The shell read this frame's window of boss flags just before the
        // tick: move the rotation past it now, while `boss_flags_to_read`
        // still names the same window (a kill or a save-reload flush below
        // would change it).
        if input.flag_reads.is_some() {
            self.advance_boss_reads();
        }
        self.frame_snapshot = input.snapshot;
        // The play clock runs while the player is in the world, the signal
        // `loading_exit` keys on, on the race save: loading screens, the
        // main menu and a wrong save (where a malus would run out at no
        // in-game cost) do not eat the race item timers. `wrong_save` is
        // set further down: a frame late at worst.
        self.play_clock.set_running(
            self.frame_snapshot.position_readable && !self.wrong_save,
            now,
        );
        self.item_feed.advance(now, self.play_clock.at(now));

        // Blackscreen IGT freeze (ported from SoulSplitter's UpdateTimer):
        // while a fade covers the screen mid-run, hold the timer at its
        // last visible value by rewriting it every frame, so load-time
        // differences between machines stop leaking into IGT. Runs BEFORE
        // the reload/quit-out block and overrides the snapshot, so that
        // block only ever sees the frozen value: the per-frame write-back
        // makes the raw IGT sawtooth, which would otherwise read as tiny
        // regressions and could arm a false quit-out.
        let raw_igt = self.frame_snapshot.igt_ms.filter(|&v| v > 0);
        let freezing = self.freeze_gate_open(now)
            && self.frame_snapshot.blackscreen == Some(true)
            && matches!(
                (raw_igt, self.freeze_last_igt),
                (Some(igt), Some(last))
                    if igt > last && igt < last.saturating_add(BLACKSCREEN_FREEZE_MAX_STEP_MS)
            );
        if freezing {
            let frozen = self.freeze_last_igt.unwrap();
            effects.push(Effect::FreezeIgt { ms: frozen });
            self.frame_snapshot.igt_ms = Some(frozen);
        } else if let Some(igt) = raw_igt {
            self.freeze_last_igt = Some(igt);
        }

        // GameDataMan's play_time reads 0 transiently while a menu reload
        // repopulates it (live-observed 2026-07-30); the status-update path
        // already treats 0 as "not in game". A real racing save's IGT is
        // never 0 when readable, so zero readings carry no information for
        // reload classification: skip them entirely (no flush, no arming,
        // no reference updates, no freeze recovery).
        if let Some(current_igt) = self.frame_snapshot.igt_ms.filter(|&v| v > 0) {
            self.first_observed_igt.get_or_insert(current_igt);
            let unload_context =
                !self.frame_snapshot.position_readable || !self.was_position_readable;
            if self.wrong_save {
                // Recovery only: a reload landing back inside the plausible
                // window of the last good observation means the race save
                // is back. Observations from the wrong save are otherwise
                // meaningless: no flush, no arming, no reference updates.
                let elapsed_ms = self
                    .last_good_at
                    .map(|t| now.duration_since(t).as_millis() as u64)
                    .unwrap_or(0);
                let good = self.last_good_igt.unwrap_or(0);
                let low = good.saturating_sub(SAVE_RELOAD_IGT_DROP_MS);
                let high = (good as u64) + elapsed_ms + WRONG_SAVE_RECOVERY_SLACK_MS as u64;
                if unload_context && current_igt >= low && (current_igt as u64) <= high {
                    info!(igt_ms = current_igt, "[RACE] Race save is back, resuming");
                    self.wrong_save = false;
                    self.last_good_igt = Some(current_igt);
                    self.last_good_at = Some(now);
                }
            } else {
                // Save reload detection: an IGT regression means the player loaded a
                // different save. Reset per-save event-flag state so a pre-set
                // finish_event from a stale save doesn't block the fresh save's real
                // finish (see EVENT_FLAG_TRACKING.md).
                if crate::core::flag_buffer::detect_save_reload(self.last_observed_igt, current_igt)
                {
                    info!(
                        prev_igt_ms = self.last_observed_igt,
                        new_igt_ms = current_igt,
                        "[RACE] Save reload detected, clearing per-save event-flag state"
                    );
                    self.triggered_flags.clear();
                    self.flag_buffer.clear_deferred();
                    self.flag_buffer.clear_pending();
                    // A fresh character is a new attempt at the run; a backup
                    // restore further in is the same attempt.
                    if current_igt <= FRESH_RUN_MAX_IGT_MS {
                        self.start_attempt();
                    }
                    // Restored flags still held are judged against the save
                    // now loaded, not the one loaded at launch.
                    if self.restored_flags.is_some() {
                        self.first_observed_igt = Some(current_igt);
                    }
                }
                // A forward IGT jump across an unload beyond WRONG_SAVE_FORWARD_SLACK_MS
                // means a different, further-along save was loaded (not the race save):
                // freeze race interaction until the race save returns.
                let forward_jump = self.has_been_in_world
                    && unload_context
                    && self.last_good_igt.is_some_and(|good| {
                        current_igt > good.saturating_add(WRONG_SAVE_FORWARD_SLACK_MS)
                    });
                if forward_jump {
                    warn!(
                        last_good_igt = self.last_good_igt,
                        new_igt_ms = current_igt,
                        "[RACE] Wrong save loaded (impossible IGT jump), freezing race interaction"
                    );
                    self.wrong_save = true;
                    self.pending_quit_out = false;
                } else {
                    // Quit-out detection: an IGT regression within SAVE_RELOAD_IGT_DROP_MS
                    // observed around an unload means a save was loaded from the menu. Death,
                    // fast travel and fog traversals reload the world, not the save;
                    // GameDataMan persists in memory and the IGT stays monotonic.
                    // Only a menu load repopulates it from disk, where the value lags
                    // the last in-memory reading by the post-flush fade time
                    // (live-measured above 1s). Map-scoped probes (MapItemMan null)
                    // proved unusable here: they also trip on cross-map fog loads.
                    // The return-to-title Lua bit (debug overlay) never fires on menu
                    // quit-outs, only on scripted returns such as endings.
                    // Rollbacks beyond SAVE_RELOAD_IGT_DROP_MS are backup restores or
                    // another save: no penalty (the per-save flush in flag_buffer covers them).
                    if self.has_been_in_world
                        && !self.pending_quit_out
                        && unload_context
                        && self.last_observed_igt.is_some_and(|prev| {
                            current_igt < prev && prev - current_igt < SAVE_RELOAD_IGT_DROP_MS
                        })
                    {
                        info!(
                            prev_igt_ms = self.last_observed_igt,
                            new_igt_ms = current_igt,
                            "[RACE] Quit-out detected (IGT regression)"
                        );
                        self.pending_quit_out = true;
                    }
                    self.last_good_igt = Some(current_igt);
                    self.last_good_at = Some(now);
                }
            }
            self.last_observed_igt = Some(current_igt);
        }
        // Before any flag read below, so a restored finish is already known,
        // and before the loading-exit zone query, which comes after them.
        self.release_restored_flags(now);
        self.flush_restored_flags(input.connected, now, &mut effects);

        if self.frame_snapshot.position_readable {
            self.has_been_in_world = true;
        }

        let position_readable = self.frame_snapshot.position_readable;

        // Reveal pending zone update once the destination is actually on
        // screen and the player position is readable. The primary signal is
        // the direct screen state (CSMenuManImp): in-game with no blackscreen
        // fade covering it. When that signal is unavailable (unmapped build
        // or unreadable chain), fall back to the legacy world-clock byte
        // (see is_world_clock_stopped), which is permanently ON on
        // frozen-clock event seeds (weather plugin FreezeTime); the
        // defensive timeout bounds the wait in that case. Both paths require
        // a readable position, so a reveal can never fire before the world
        // is loaded.
        if self.pending_zone_update.is_some() {
            let pending_for = self.pending_zone_received_at.map(|t| now.duration_since(t));
            let timed_out = pending_for.is_some_and(|d| d >= ZONE_REVEAL_TIMEOUT);
            let loading_done = match self.frame_snapshot.screen_in_game {
                // Direct signal (CSMenuManImp): the destination is on
                // screen when the menu system reports in-game and no fade
                // covers it. Immune to the world-clock failure modes
                // (cutscenes, frozen-clock event seeds).
                Some(in_game) => in_game && self.frame_snapshot.blackscreen == Some(false),
                // Unmapped build or unreadable chain: legacy proxy.
                None => self.frame_snapshot.loading_screen != Some(true),
            };
            if position_readable && (loading_done || timed_out) {
                let zone = self.pending_zone_update.take().unwrap();
                let (unused_exits, defeat_flag) = (zone.unused_exits, zone.defeat_flag);
                if loading_done {
                    info!(name = %zone.display_name, ?unused_exits, ?defeat_flag, "[RACE] Zone revealed");
                } else {
                    warn!(name = %zone.display_name, ?unused_exits, ?defeat_flag, "[RACE] Zone revealed (timeout, reveal signal stuck)");
                }
                self.race_state.current_zone = Some(zone);
                let start = self.ink_start(self.race_state.current_zone.as_ref());
                if self.item_feed.decide_ink(start, self.play_clock.at(now)) {
                    log_ink(start, "zone revealed");
                }
                self.zone_version = self.zone_version.wrapping_add(1);
                self.pre_reveal_layer = None;
                self.pending_zone_received_at = None;
                self.zone_stall_warned = false;
                // A zone entry is a checkpoint of a live holder's state (dropped
                // below when the socket is down).
                if self.relay_holder_live() {
                    self.relay_checkpoint_due = true;
                }
            } else if !self.zone_stall_warned
                && pending_for.is_some_and(|d| d >= ZONE_REVEAL_STALL_WARN)
            {
                let zone = self.pending_zone_update.as_ref().unwrap();
                warn!(
                    name = %zone.display_name,
                    pending_secs = pending_for.unwrap().as_secs(),
                    position_readable,
                    "[RACE] Zone reveal still pending (position readability broken or flickering, or player idling in a menu)"
                );
                self.zone_stall_warned = true;
            }
        }

        // Flags cleared (captured) earlier in this tick: later read consumers
        // must treat them as unset, mirroring the pre-machine behavior where
        // each stage re-read memory after the previous stage's clears.
        let mut cleared: HashSet<u32> = HashSet::new();
        // Set when the quit-out penalty below pulls `last_status_update`
        // into the past: without this, the generic periodic check further
        // down (same tick, same `now`) would immediately see the gate open
        // and consume the pull-forward itself, so the *next* tick (the one
        // actually meant to benefit) would see no elapsed time and skip.
        let mut quit_out_status_pulled_forward = false;

        // Loading screen exit: send deferred event_flags (certain) or zone_query (probabilistic)
        let loading_exit = position_readable && !self.was_position_readable;
        if loading_exit {
            self.last_loading_exit = Some(now);
            let quit_out = std::mem::take(&mut self.pending_quit_out);
            // Reloading the save must not shake the Hunter off; any other
            // load ends his hunt, on his way back too.
            if quit_out {
                if self.hunter.quit_out(now) {
                    info!(
                        "[ITEMS] Quit-out during a hunt: the Hunter comes back once the player settles"
                    );
                }
            } else if self.hunter.load() {
                info!("[ITEMS] A load on the Hunter's way back ends the hunt");
            }
            if quit_out
                && self.is_race_running()
                && !self.am_i_finished()
                && !self.is_countdown_active(now)
            {
                let penalty_ms = self.quit_out_penalty_ms();
                if penalty_ms > 0 {
                    effects.push(Effect::ApplyIgtPenalty { ms: penalty_ms });
                    // The write invalidates the frozen baseline; the next
                    // clear frame re-seeds it from the penalized IGT (one
                    // unfrozen fade frame at worst).
                    self.freeze_last_igt = None;
                    let banner = if penalty_ms % 1000 == 0 {
                        format!("Quit-out: +{}s", penalty_ms / 1000)
                    } else {
                        format!("Quit-out: +{:.1}s", penalty_ms as f32 / 1000.0)
                    };
                    self.set_status(banner, now);
                    // Pull the next periodic status_update forward so the
                    // leaderboard reflects the bumped IGT immediately.
                    self.last_status_update = now
                        .checked_sub(Duration::from_secs(2))
                        .unwrap_or(self.last_status_update);
                    quit_out_status_pulled_forward = true;
                    info!(penalty_ms, "[RACE] Quit-out penalty applied");
                }
            }

            // Force one immediate flag scan to catch flags set during loading
            // (e.g. Erdtree burn, Maliketh warp) that the 10Hz poll couldn't read
            // because is_flag_set() returns None while position is unreadable.
            // Skipped while frozen: no flag writes into a foreign save.
            if !self.event_ids.is_empty() && !self.wrong_save {
                let igt_ms = self.effective_igt_ms();
                if let Some(ref reads) = input.flag_reads {
                    for &(flag_id, is_set) in reads {
                        if !is_set {
                            continue;
                        }
                        if self.boss_flags.binary_search(&flag_id).is_ok() {
                            self.capture_boss_kill(
                                flag_id,
                                igt_ms,
                                input.connected,
                                now,
                                &mut effects,
                            );
                            continue;
                        }
                        if self.item_use_flags.binary_search(&flag_id).is_ok() {
                            self.capture_item_use(
                                flag_id,
                                igt_ms,
                                input.connected,
                                now,
                                &mut cleared,
                                &mut effects,
                            );
                            continue;
                        }
                        if self.finish_event == Some(flag_id) {
                            if !self.triggered_flags.contains(&flag_id) {
                                self.triggered_flags.insert(flag_id);
                                self.record_capture(flag_id, igt_ms, now);
                                if input.connected
                                    && self.is_race_running()
                                    && !self.am_i_finished()
                                    && !self.is_countdown_active(now)
                                {
                                    effects.push(self.queue_event_flag(flag_id, igt_ms));
                                    self.last_sent_debug = Some(format!(
                                        "event_flag({}, igt={}ms) [finish/loading-exit]",
                                        flag_id, igt_ms
                                    ));
                                    info!(flag_id, "[RACE] Finish event caught at loading exit");
                                } else if !self.am_i_finished() {
                                    self.flag_buffer.add_pending(flag_id, igt_ms);
                                }
                            }
                        } else {
                            effects.push(Effect::SetGameFlag {
                                flag_id,
                                value: false,
                            });
                            cleared.insert(flag_id);
                            self.flag_buffer.defer(flag_id, igt_ms);
                            self.record_capture(flag_id, igt_ms, now);
                            info!(flag_id, "[RACE] Event flag caught at loading exit");
                        }
                    }
                }
            }

            if input.connected
                && self.is_race_running()
                && !self.am_i_finished()
                && !self.is_countdown_active(now)
                && !self.wrong_save
            {
                if self.flag_buffer.has_deferred() {
                    // Fog gate traversal: send deferred flags now that loading is done
                    let deferred: Vec<_> = self.flag_buffer.drain_deferred().collect();
                    for (flag_id, igt_ms) in deferred {
                        effects.push(self.queue_event_flag(flag_id, igt_ms));
                        self.last_sent_debug = Some(format!(
                            "event_flag({}, igt={}ms) [deferred]",
                            flag_id, igt_ms
                        ));
                        info!(flag_id, "[RACE] Deferred event flag sent at loading exit");
                    }
                } else {
                    // No fog gate (death/respawn/quit-out/fast-travel)
                    let igt_ms = self.effective_igt_ms();
                    let grace_opt = input.warp_capture;
                    let map_id = input.position.as_ref().map(|p| p.map_id_str.clone());
                    let position = input.position.as_ref().map(|p| [p.x, p.y, p.z]);
                    let play_region_id = input.position.as_ref().and_then(|p| p.play_region_id);

                    if grace_opt.is_some() || map_id.is_some() {
                        effects.push(self.queue_zone_query(
                            igt_ms,
                            grace_opt,
                            map_id.clone(),
                            position,
                            play_region_id,
                            quit_out,
                        ));
                        self.last_sent_debug = Some(format!(
                            "zone_query(grace={:?}, map={:?})",
                            grace_opt, map_id
                        ));
                        info!(?grace_opt, "[RACE] Zone query sent at loading exit");
                    }

                    if grace_opt.is_some() {
                        effects.push(Effect::ClearWarpCapture);
                    }
                }
            } else {
                // Disconnected during a live race: buffer deferred flags for
                // re-send on reconnect (they are already cleared from game
                // memory, so the safety-net rescan cannot recover them).
                if self.is_race_running() && !self.am_i_finished() {
                    let count = self.flag_buffer.park_deferred();
                    if count > 0 {
                        info!(
                            count,
                            "[RACE] Deferred flags moved to pending (disconnected)"
                        );
                    }
                } else {
                    self.flag_buffer.clear_deferred();
                }
                if input.warp_capture.is_some() {
                    effects.push(Effect::ClearWarpCapture);
                }
            }
        }
        self.was_position_readable = position_readable;

        // Event flag polling runs ALWAYS (even when disconnected).
        // Regular flags are cleared after capture (for re-traversal detection) and
        // deferred until loading exit; finish_event is sent immediately.
        let poll_due = !self.event_ids.is_empty()
            && now.duration_since(self.last_flag_poll) >= Duration::from_millis(100);
        // Record the reader health on every read frame (the shell logs the
        // transition when it performs the reads; recording here keeps the
        // transition from being re-logged on subsequent read frames).
        if let Some(ok) = input.flag_reader_ok {
            self.last_flag_reader_ok = Some(ok);
        }
        if poll_due && !self.wrong_save {
            if let Some(ref reads) = input.flag_reads {
                self.last_flag_poll = now;

                let igt_ms = self.effective_igt_ms();
                for &(flag_id, is_set) in reads {
                    if !is_set || cleared.contains(&flag_id) {
                        continue;
                    }
                    if self.boss_flags.binary_search(&flag_id).is_ok() {
                        self.capture_boss_kill(flag_id, igt_ms, input.connected, now, &mut effects);
                        continue;
                    }
                    if self.item_use_flags.binary_search(&flag_id).is_ok() {
                        self.capture_item_use(
                            flag_id,
                            igt_ms,
                            input.connected,
                            now,
                            &mut cleared,
                            &mut effects,
                        );
                        continue;
                    }
                    if self.finish_event == Some(flag_id) {
                        // finish_event: one-shot, use triggered_flags guard
                        if !self.triggered_flags.contains(&flag_id) {
                            self.triggered_flags.insert(flag_id);
                            self.record_capture(flag_id, igt_ms, now);
                            if input.connected
                                && self.is_race_running()
                                && !self.am_i_finished()
                                && !self.is_countdown_active(now)
                            {
                                effects.push(self.queue_event_flag(flag_id, igt_ms));
                                self.last_sent_debug = Some(format!(
                                    "event_flag({}, igt={}ms) [finish]",
                                    flag_id, igt_ms
                                ));
                                info!(flag_id, "[RACE] Finish event sent immediately");
                            } else if !self.am_i_finished() {
                                self.flag_buffer.add_pending(flag_id, igt_ms);
                            }
                        }
                    } else {
                        // Regular fog gate: clear after capture so re-traversals are detected
                        effects.push(Effect::SetGameFlag {
                            flag_id,
                            value: false,
                        });
                        cleared.insert(flag_id);
                        self.flag_buffer.defer(flag_id, igt_ms);
                        self.record_capture(flag_id, igt_ms, now);
                        info!(flag_id, "[RACE] Event flag deferred until loading exit");
                    }
                }
            }
        }

        // Deathless: a strict local death-count increase while racing fires
        // the one-shot "You died" banner. Elimination itself is server-side
        // (the periodic status_update carries the count); this is instant
        // local feedback only, so it also works while disconnected.
        if let Some(deaths) = self.frame_snapshot.death_count {
            if let Some(prev) = self.last_seen_death_count {
                if deaths > prev
                    && !self.deathless_banner_shown
                    && self.is_deathless()
                    && self.is_race_running()
                    && !self.is_countdown_active(now)
                    && !self.am_i_finished()
                    && !self.am_i_abandoned()
                    && !self.wrong_save
                {
                    self.deathless_banner_shown = true;
                    self.set_status("You died. Race over.".to_string(), now);
                    info!(deaths, "[RACE] Deathless death detected");
                }
            }
            self.last_seen_death_count = Some(deaths);
        }

        // Cheat detection: the game's debug-flag bytes, read at 10 Hz while
        // racing. The mask is cumulative since the race start, so a short
        // toggle between two status updates is still reported; the banner
        // follows the latest read. Closing the gate (finish, wrong save,
        // race end) drops the banner.
        if self.debug_flags_gate_open(now) {
            if now.duration_since(self.last_debug_flags_poll) >= Duration::from_millis(100) {
                self.last_debug_flags_poll = now;
                if let Some(mask) = self.frame_snapshot.debug_flags {
                    if self.debug_flags_last != Some(mask) {
                        info!("[RACE] Debug flags: {mask:#x}");
                    }
                    self.debug_flags_seen |= mask;
                    self.debug_flags_last = Some(mask);
                }
            }
        } else {
            self.debug_flags_last = None;
            // The server rejects the updates of this save (fresh save
            // required, wrong save): whatever was seen belongs to a save that
            // is not the race run, so it must not reach the next accepted one.
            if self.get_blocking_condition(now).is_some() {
                self.debug_flags_seen = 0;
            }
        }

        // Everything below needs a live connection (ready, replays, status updates).
        if !input.connected {
            // No report without a connection: the reconnect frame sends it.
            // The effects are local: a load gets them back all the same.
            self.flush_race_items(false, loading_exit, loading_exit, now, &mut effects);
            self.maintain_memory_effects(loading_exit, now, &mut effects);
            self.maintain_hunter(now, &mut effects);
            self.relay_link_lost();
            self.maintain_relay(false, loading_exit, now, &mut effects);
            return effects;
        }

        let igt_ms = self.frame_snapshot.igt_ms.unwrap_or(0);
        let deaths = self.frame_snapshot.death_count.unwrap_or(0);

        // Send ready on (re)connection (skip in training mode since server auto-starts)
        let reconnect_frame = !self.ready_sent;
        if !self.ready_sent {
            if !self.training {
                effects.push(Effect::SendReady);
                self.last_sent_debug = Some("ready".to_string());
                info!("[RACE] Sent ready signal");
            }
            self.ready_sent = true;

            if self.is_race_running() && !self.am_i_finished() && !self.is_countdown_active(now) {
                self.flush_restored = false;

                // Replay in-flight event flags (sent but not ACKed before disconnect)
                // with their original message_id for server-side dedup.
                self.replay_in_flight_event_flags(&mut effects);

                // Replay in-flight zone queries (sent but not ACKed before disconnect)
                self.replay_in_flight_zone_queries(&mut effects);

                // Drain event flags buffered during disconnection (never sent)
                self.send_pending_event_flags(&mut effects);

                // Safety-net rescan: catch any flags still set in memory that polling missed
                if let Some(ref reads) = input.flag_reads {
                    for &(flag_id, is_set) in reads {
                        if !is_set || cleared.contains(&flag_id) {
                            continue;
                        }
                        if self.boss_flags.binary_search(&flag_id).is_ok() {
                            // The held IGT, as the other scans: a reload's
                            // transient 0 would lose the kill (the server
                            // ignores a kill at IGT 0).
                            let kill_igt_ms = self.effective_igt_ms();
                            self.capture_boss_kill(
                                flag_id,
                                kill_igt_ms,
                                input.connected,
                                now,
                                &mut effects,
                            );
                            continue;
                        }
                        if self.item_use_flags.binary_search(&flag_id).is_ok() {
                            // The held IGT too, for the same reason.
                            let use_igt_ms = self.effective_igt_ms();
                            self.capture_item_use(
                                flag_id,
                                use_igt_ms,
                                input.connected,
                                now,
                                &mut cleared,
                                &mut effects,
                            );
                            continue;
                        }
                        if self.finish_event == Some(flag_id) {
                            if !self.triggered_flags.contains(&flag_id) {
                                self.triggered_flags.insert(flag_id);
                                self.record_capture(flag_id, igt_ms, now);
                                effects.push(self.queue_event_flag(flag_id, igt_ms));
                                self.last_sent_debug =
                                    Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                                info!(flag_id, "[RACE] Finish event re-sent after reconnect");
                            }
                        } else {
                            effects.push(Effect::SetGameFlag {
                                flag_id,
                                value: false,
                            });
                            cleared.insert(flag_id);
                            self.record_capture(flag_id, igt_ms, now);
                            effects.push(self.queue_event_flag(flag_id, igt_ms));
                            self.last_sent_debug =
                                Some(format!("event_flag({}, igt={})", flag_id, igt_ms));
                            info!(flag_id, "[RACE] Event flag re-sent after reconnect");
                        }
                    }
                }
            }
        }

        // After every flag of the frame (replays, buffered, scans): a use
        // made just before a quit-out reaches the server before the
        // inventory that no longer holds it.
        // A reconnection is no load: the game kept the effects.
        let load_or_reconnect = loading_exit || reconnect_frame;
        self.flush_race_items(
            load_or_reconnect,
            load_or_reconnect,
            loading_exit,
            now,
            &mut effects,
        );
        self.maintain_memory_effects(loading_exit, now, &mut effects);
        self.maintain_hunter(now, &mut effects);
        self.maintain_relay(true, loading_exit, now, &mut effects);

        // Send periodic status updates (every 1 second, only when IGT is ticking and race running)
        // During quit-outs IGT is 0, skip to avoid erroneous data.
        // Stop once finished since IGT is frozen at finish time.
        if !quit_out_status_pulled_forward
            && !self.wrong_save
            && self.wants_status_update(now, igt_ms)
        {
            effects.push(Effect::SendStatusUpdate {
                igt_ms,
                death_count: deaths,
                weapons: input.weapons,
                debug_flags: self.debug_flags_seen,
            });
            self.last_status_update = now;
        }

        effects
    }

    /// Send the restored flags once `ready` went out: they are usually
    /// restored when the save loads, well after the mod connected on the
    /// title screen. Same sends as a reconnection, without waiting for one;
    /// before `ready`, the reconnection sends them.
    fn flush_restored_flags(&mut self, connected: bool, now: Instant, effects: &mut Vec<Effect>) {
        if !self.flush_restored
            || !connected
            || !self.ready_sent
            || !self.is_race_running()
            || self.am_i_finished()
            || self.is_countdown_active(now)
        {
            return;
        }
        self.flush_restored = false;
        self.replay_in_flight_event_flags(effects);
        self.send_pending_event_flags(effects);
    }

    /// A boss defeat flag found set by a scan, the single place one is
    /// handled. Reported once (`triggered_flags`, which a save reload
    /// clears), at once rather than at the next loading exit, and never
    /// cleared in game memory: clearing a defeat flag would bring the boss
    /// back. Sent while connected, `ready` out and past the countdown,
    /// buffered in the pending flags otherwise: on the frame the connection
    /// comes back, `ready` and the replay of the flags still in flight (a
    /// fog into the boss's node among them) go first, and the same frame
    /// drains the pending flags after them. While the race is not running
    /// or the runner has finished or is out, it is left unmarked, so a scan
    /// of the live run reports it. A kill is no depth arrival: it never
    /// reaches `record_capture`. The kill of the newest zone's boss runs an
    /// ink held in its arena (`ink_start`): the arena's exits open now.
    fn capture_boss_kill(
        &mut self,
        flag_id: u32,
        igt_ms: u32,
        connected: bool,
        now: Instant,
        effects: &mut Vec<Effect>,
    ) {
        if self.triggered_flags.contains(&flag_id)
            || !self.is_race_running()
            || self.am_i_finished()
            || self.am_i_abandoned()
        {
            return;
        }
        self.triggered_flags.insert(flag_id);
        let arena_start = self
            .pending_zone_update
            .as_ref()
            .or(self.race_state.current_zone.as_ref())
            .filter(|z| z.defeat_flag == Some(flag_id))
            .map(|z| self.ink_start(Some(z)));
        if let Some(start) = arena_start {
            if self.item_feed.decide_ink(start, self.play_clock.at(now)) {
                log_ink(start, "boss killed");
            }
        }
        if connected && self.ready_sent && !self.is_countdown_active(now) {
            effects.push(self.queue_event_flag(flag_id, igt_ms));
            self.last_sent_debug =
                Some(format!("event_flag({}, igt={}ms) [boss]", flag_id, igt_ms));
            info!(flag_id, igt_ms, "[RACE] Boss kill sent");
        } else {
            self.flag_buffer.add_pending(flag_id, igt_ms);
            info!(flag_id, igt_ms, "[RACE] Boss kill buffered");
        }
    }

    /// A race item use flag found set by a scan, the single place one is
    /// handled. The game raises it on every use: it is cleared in game at
    /// once (and added to `cleared`, so the frame's later scans skip it) for
    /// the next use to raise it again, never joins `triggered_flags`, and is
    /// no depth arrival. Sent like a boss kill: at once while connected,
    /// `ready` out and past the countdown, buffered in the pending flags
    /// otherwise. Left set while the run is not live, so a scan of the live
    /// run reports it. The game consumed the goods: the item held as it, and
    /// its row, go.
    fn capture_item_use(
        &mut self,
        flag_id: u32,
        igt_ms: u32,
        connected: bool,
        now: Instant,
        cleared: &mut HashSet<u32>,
        effects: &mut Vec<Effect>,
    ) {
        if !self.is_race_running() || self.am_i_finished() || self.am_i_abandoned() {
            return;
        }
        effects.push(Effect::SetGameFlag {
            flag_id,
            value: false,
        });
        cleared.insert(flag_id);
        if self
            .held_item
            .as_deref()
            .is_some_and(|item| self.item_used_by(item, flag_id))
        {
            self.held_item = None;
        }
        if self
            .item_feed
            .held()
            .is_some_and(|row| self.item_used_by(&row.key, flag_id))
        {
            self.item_feed.set_held(None);
        }
        if connected && self.ready_sent && !self.is_countdown_active(now) {
            effects.push(self.queue_event_flag(flag_id, igt_ms));
            self.last_sent_debug = Some(format!(
                "event_flag({}, igt={}ms) [item use]",
                flag_id, igt_ms
            ));
            info!(flag_id, igt_ms, "[ITEMS] Item use sent");
        } else {
            self.flag_buffer.add_pending(flag_id, igt_ms);
            info!(flag_id, igt_ms, "[ITEMS] Item use buffered");
        }
    }

    /// Race item work held for a loaded frame on the race save, run after
    /// the frame's flag scans, in this order: the inventory report
    /// (`report_inventory`: a game load or a reconnection, while connected),
    /// preceded by the held item's icon write (a game restart reloads the
    /// params), the grant spawns, each preceded by its item's icon write
    /// (the failed ones again only when `retry_grants`: a game load or a
    /// reconnection), the timed effects with time left applied again with
    /// it (`loading_exit`: a game load, which dropped them), then the
    /// pending effects, whose banner, reminder and duration start now (an
    /// ink applied on a loading exit waits for the next zone reveal; a
    /// memory effect starts on the play clock, `maintain_memory_effects`
    /// writes it). A
    /// grant's banner waits for its spawn's outcome (`grant_spawn_result`).
    /// An outdated seed pack holds it all: its regulation may lack the race
    /// goods and their effects. A run that is over drops it all.
    fn flush_race_items(
        &mut self,
        report_inventory: bool,
        retry_grants: bool,
        loading_exit: bool,
        now: Instant,
        effects: &mut Vec<Effect>,
    ) {
        // The shell answers a spawn within the batch that asked for it: one
        // still unanswered here lost its batch (a frame that panicked is
        // skipped whole) and would otherwise wait for ever, every resend
        // of its grant taken for a spawn under way.
        if !self.spawning_grants.is_empty() {
            warn!(
                count = self.spawning_grants.len(),
                "[ITEMS] Grant spawns never answered, retried at the next load or reconnection"
            );
            self.retry_grants.append(&mut self.spawning_grants);
        }
        // Once the run is over (race not running, runner finished or out),
        // what still waits is dropped rather than held for a load.
        if !self.is_race_running() || self.am_i_finished() || self.am_i_abandoned() {
            self.drop_waiting_race_items("run not live", effects);
            return;
        }
        if !self.frame_snapshot.position_readable || self.wrong_save || self.seed_mismatch {
            return;
        }
        // Without a catalog, the race goods are unknown: an empty report
        // would read as every item lost.
        if report_inventory && !self.item_inventory_goods.is_empty() && self.race_items_on() {
            let icon = self.held_item.as_deref().and_then(|item| {
                self.item_and_goods(item)
                    .map(|(entry, goods)| (goods.goods_id, entry.icon_id))
            });
            if let Some((goods_id, icon_id)) = icon {
                info!(goods_id, icon_id, "[ITEMS] Held item's icon requested");
                effects.push(Effect::SetGoodsIcon { goods_id, icon_id });
            }
            info!("[ITEMS] Inventory report");
            effects.push(Effect::ReportItemInventory {
                goods: self.item_inventory_goods.clone(),
            });
        }
        let retries = if retry_grants {
            std::mem::take(&mut self.retry_grants)
        } else {
            Vec::new()
        };
        for grant in retries
            .into_iter()
            .chain(std::mem::take(&mut self.pending_grants))
        {
            info!(grant_id = grant.grant_id, "[ITEMS] Grant spawn requested");
            effects.push(Effect::SetGoodsIcon {
                goods_id: grant.goods_id,
                icon_id: grant.icon_id,
            });
            effects.push(Effect::SpawnRaceItem {
                grant_id: grant.grant_id,
                goods_id: grant.goods_id,
            });
            self.spawning_grants.push(grant);
        }
        let play = self.play_clock.at(now);
        if loading_exit {
            // An equip load effect comes back as its SpEffect alone: the
            // rate written at its application stays in its row.
            self.timed_effects.prune(play);
            for (speffect_id, left) in self.timed_effects.live(play) {
                let left_ms = u32::try_from(left.as_millis()).unwrap_or(u32::MAX);
                info!(speffect_id, left_ms, "[ITEMS] Effect applied again");
                effects.push(Effect::ApplySpEffect {
                    speffect_id,
                    left_ms: Some(left_ms),
                });
            }
        }
        for effect in std::mem::take(&mut self.pending_item_effects) {
            info!(action = ?effect.action, "[ITEMS] Effect applied");
            let mut reminder = effect.reminder;
            let mut banner = effect.banner;
            match effect.action {
                ItemAction::Shell(apply) => {
                    if let Effect::ApplySpEffect {
                        speffect_id,
                        left_ms: Some(duration_ms),
                    }
                    | Effect::ApplyEquipLoad {
                        speffect_id,
                        left_ms: Some(duration_ms),
                        ..
                    } = apply
                    {
                        self.timed_effects.start(
                            speffect_id,
                            Duration::from_millis(u64::from(duration_ms)),
                            play,
                        );
                    }
                    effects.push(apply);
                }
                ItemAction::Ink(duration) => {
                    // The reminder is the ink's own row, not a timed one; the
                    // ink waits while the zone has no unused exit to hide,
                    // and is held in a boss arena whose boss lives
                    // (`ink_start`). The newest zone decides: the one a
                    // pending reveal brings, else the current one (no zone
                    // at all runs it). On a loading exit the destination's
                    // zone_update has not come yet (the fog flags deferred to
                    // this exit go out on this frame): it waits, and the
                    // next reveal decides.
                    let row = reminder.take().map(|r| FeedRow {
                        icon: effect.icon.clone(),
                        text: r.text,
                        tone: FeedTone::Malus,
                    });
                    let zone = self
                        .pending_zone_update
                        .as_ref()
                        .or(self.race_state.current_zone.as_ref());
                    let start = if loading_exit {
                        InkStart::Wait
                    } else {
                        self.ink_start(zone)
                    };
                    if self.item_feed.hit_ink(row, duration, start, play) {
                        log_ink(start, if loading_exit { "loading exit" } else { "hit" });
                    }
                }
                // Written by `maintain_memory_effects`, on this same frame.
                ItemAction::Memory(memory, duration) => {
                    self.memory_effects.start(memory, duration, play);
                    // The effect of the kind it replaces loses its row; a
                    // row of the same text is merged by `add_reminder`.
                    let kind = discriminant(&memory);
                    let text = reminder.as_ref().map(|r| r.text.clone());
                    if let Some(i) = self.memory_reminders.iter().position(|(k, _)| *k == kind) {
                        let (_, previous) = self.memory_reminders.swap_remove(i);
                        if text.as_ref() != Some(&previous) {
                            self.item_feed.remove_reminder(&previous);
                        }
                    }
                    if let Some(text) = text {
                        self.memory_reminders.push((kind, text));
                    }
                }
                // The slow walk as any timed SpEffect (applied again with
                // its time left after a load), the shrink as a memory scale.
                // The scale it replaces (a Giant) loses its row; its own row
                // is its timed reminder below, not a memory one, so a later
                // Giant replacing the shrink leaves it to the slow walk.
                ItemAction::Lightning {
                    speffect_id,
                    scale,
                    duration,
                } => {
                    self.timed_effects.start(speffect_id, duration, play);
                    effects.push(Effect::ApplySpEffect {
                        speffect_id,
                        left_ms: Some(u32::try_from(duration.as_millis()).unwrap_or(u32::MAX)),
                    });
                    let memory = MemoryEffect::Scale { scale };
                    self.memory_effects.start(memory, duration, play);
                    let kind = discriminant(&memory);
                    if let Some(i) = self.memory_reminders.iter().position(|(k, _)| *k == kind) {
                        let (_, previous) = self.memory_reminders.swap_remove(i);
                        self.item_feed.remove_reminder(&previous);
                    }
                }
                // His banner and reminder wait for him (`maintain_hunter`).
                ItemAction::Hunter(mut spec) => {
                    spec.notice = HunterNotice {
                        banner: banner.take(),
                        icon: effect.icon.clone(),
                        reminder: reminder.take(),
                    };
                    let report_id = spec.report_id;
                    if self.hunter.start(spec, now) {
                        info!(report_id, "[ITEMS] Hunter sent out");
                    } else {
                        // One at a time: the sender learns this one missed.
                        info!(
                            report_id,
                            "[ITEMS] Hunter missed, another one is awaited or hunting"
                        );
                        effects.push(Effect::SendItemReport {
                            report_id,
                            landed: false,
                            talisman_id: None,
                        });
                    }
                }
            }
            if let Some(reminder) = reminder {
                self.item_feed.add_reminder(
                    effect.icon,
                    reminder.text,
                    FeedTone::Malus,
                    Duration::from_millis(u64::from(reminder.duration_ms)),
                    play,
                );
            }
            if let Some(banner) = banner {
                self.item_feed.push_banner(banner, now);
            }
        }
    }

    /// Drop the race item work waiting for a load: grants, failed spawns,
    /// effects (logged when any was waiting), the timed effects a load
    /// would apply again (the game runs out the ones it holds), the
    /// memory effects (the next loaded frame writes their defaults back)
    /// and the Hunter (`drop_hunter`).
    fn drop_waiting_race_items(&mut self, reason: &'static str, effects: &mut Vec<Effect>) {
        let grants = self.pending_grants.len() + self.retry_grants.len();
        let item_effects = self.pending_item_effects.len();
        if grants + item_effects > 0 {
            info!(
                grants,
                item_effects, reason, "[ITEMS] Waiting race items dropped"
            );
        }
        self.pending_grants.clear();
        self.retry_grants.clear();
        self.pending_item_effects.clear();
        self.timed_effects.clear();
        self.memory_effects.clear();
        // Their rows go with them: the defaults are written back at once,
        // unlike a timed SpEffect, which the game runs out under its row.
        for (_, text) in self.memory_reminders.drain(..) {
            self.item_feed.remove_reminder(&text);
        }
        self.item_feed.drop_unstarted_ink();
        self.drop_hunter(reason, effects);
    }

    /// Forget the Hunter; one requested and not missed yet, hunting, or
    /// still watched after his last miss may be in the world: ended
    /// (`EndHunter`), wherever the player is. His reminder row goes too.
    fn drop_hunter(&mut self, reason: &'static str, effects: &mut Vec<Effect>) {
        let npc_param_id = self.hunter.spec().map(|spec| spec.npc_param_id);
        if let (true, Some(npc_param_id)) = (self.hunter.clear(), npc_param_id) {
            info!(npc_param_id, reason, "[ITEMS] Hunter ended");
            effects.push(Effect::EndHunter { npc_param_id });
        }
        self.drop_hunter_row();
    }

    /// What `zone`, the zone that decides, makes of an ink not run yet (no
    /// zone known runs it). A zone with no exit no edge takes
    /// (`unused_exits` 0: every fog leads on, hiding them costs the runner
    /// nothing) lets it wait, the exits readable. Otherwise (unused exits,
    /// or a count the mod does not know: a seed older than graph.json 4.13)
    /// a boss arena whose boss lives (`defeat_flag` not killed yet) holds
    /// it, the exits hidden through the fight and its time running from the
    /// kill (`capture_boss_kill`), and any other zone runs it.
    fn ink_start(&self, zone: Option<&ZoneUpdateData>) -> InkStart {
        let Some(zone) = zone else {
            return InkStart::Run;
        };
        if zone.unused_exits == Some(0) {
            InkStart::Wait
        } else if zone
            .defeat_flag
            .is_some_and(|flag| !self.triggered_flags.contains(&flag))
        {
            InkStart::Hold
        } else {
            InkStart::Run
        }
    }

    /// Keep the memory race item effects in the game, right after
    /// `flush_race_items` (which starts them), on a loaded frame: emit
    /// `ApplyMemoryState` when the state they give changes, at a loading
    /// exit (a load may reset what was written) and, while any is live,
    /// every `MEMORY_REFRESH_INTERVAL` of wall time, the foes walked when
    /// hidden or shown, through a load and every `FOES_WALK_INTERVAL` while
    /// hidden (for the characters loaded since). A wrong save gets the
    /// defaults once, the effects kept with their time left (the play clock
    /// stops there) for the race save's next loading exit. Once none is
    /// live (ended, or dropped with the run: run over, new start, another
    /// participant), the defaults are written once.
    fn maintain_memory_effects(
        &mut self,
        loading_exit: bool,
        now: Instant,
        effects: &mut Vec<Effect>,
    ) {
        // Nothing to write into while the player is not loaded: the next
        // loaded frame writes the state.
        if !self.frame_snapshot.position_readable {
            return;
        }
        let play = self.play_clock.at(now);
        let (state, walk_foes) = if !self.wrong_save && self.memory_effects.any_live(play) {
            let state = self.memory_effects.state(play);
            let walk_due = state.foes_hidden
                && now.saturating_duration_since(self.foes_walked_at) >= FOES_WALK_INTERVAL;
            let refresh_due =
                now.saturating_duration_since(self.memory_written_at) >= MEMORY_REFRESH_INTERVAL;
            if state == self.memory_written && !loading_exit && !walk_due && !refresh_due {
                return;
            }
            let walk_foes = state.foes_hidden != self.memory_written.foes_hidden
                || (state.foes_hidden && (loading_exit || walk_due));
            (state, walk_foes)
        } else {
            if !self.wrong_save {
                self.memory_effects.clear();
                self.memory_reminders.clear();
            }
            if self.memory_written == MemoryState::default() {
                return;
            }
            // Shows back the foes the last walks hid.
            (MemoryState::default(), self.memory_written.foes_hidden)
        };
        if state != self.memory_written {
            info!(
                ?state,
                walk_foes,
                loading_exit,
                wrong_save = self.wrong_save,
                "[ITEMS] Memory state changed"
            );
        }
        self.memory_written = state;
        self.memory_written_at = now;
        if walk_foes {
            self.foes_walked_at = now;
        }
        effects.push(Effect::ApplyMemoryState { state, walk_foes });
    }

    /// Run the Hunter's life (`core::hunter`), right after
    /// `maintain_memory_effects`, on a loaded frame of the race save: his
    /// spawn once the player has been loaded `hunter::SETTLE` since the last
    /// loading exit (his return after a quit-out too), the looks for him, his
    /// end, the report, and his banner and reminder once found (the row goes
    /// when the hunt does, see `drop_hunter_row`). A few comparisons while
    /// nothing is due.
    fn maintain_hunter(&mut self, now: Instant, effects: &mut Vec<Effect>) {
        if !self.frame_snapshot.position_readable || self.wrong_save {
            return;
        }
        let settled = self
            .last_loading_exit
            .is_none_or(|at| now.saturating_duration_since(at) >= hunter::SETTLE);
        let play = self.play_clock.at(now);
        for step in self.hunter.tick(now, play, settled) {
            let Some(&HunterSpec {
                chr_id,
                npc_param_id,
                think_id,
                report_id,
                ..
            }) = self.hunter.spec()
            else {
                break;
            };
            match step {
                HunterStep::Request => {
                    info!(
                        report_id,
                        chr_id, npc_param_id, think_id, "[ITEMS] Hunter spawn requested"
                    );
                    effects.push(Effect::RequestHunter {
                        chr_id,
                        npc_param_id,
                        think_id,
                    });
                }
                HunterStep::Find => effects.push(Effect::FindHunter { npc_param_id }),
                HunterStep::End => {
                    info!(npc_param_id, "[ITEMS] Hunter ended");
                    effects.push(Effect::EndHunter { npc_param_id });
                    // A miss on his way back after a quit-out keeps the
                    // hunt, and its row.
                    if !self.hunter.is_hunting() {
                        self.drop_hunter_row();
                    }
                }
                HunterStep::Report { landed } => {
                    info!(report_id, landed, "[ITEMS] Hunter reported");
                    effects.push(Effect::SendItemReport {
                        report_id,
                        landed,
                        talisman_id: None,
                    });
                }
                HunterStep::Found => {
                    info!(report_id, "[ITEMS] Hunter found, he hunts");
                    let notice = self.hunter.take_notice();
                    self.hunter_row = notice.reminder.as_ref().map(|r| r.text.clone());
                    if let Some(reminder) = notice.reminder {
                        self.item_feed.add_reminder(
                            notice.icon,
                            reminder.text,
                            FeedTone::Malus,
                            Duration::from_millis(u64::from(reminder.duration_ms)),
                            play,
                        );
                    }
                    if let Some(banner) = notice.banner {
                        self.item_feed.push_banner(banner, now);
                    }
                }
            }
        }
    }

    /// What the relay lock should read, from the server's word alone: `None`
    /// leaves the flag alone (no relay, or a value this build does not
    /// know: an unknown value is never a decision). Over, or a race that
    /// does not run, wins over the role. A relay not being played reads
    /// off; a live one locks a waiting runner and a capped holder.
    fn relay_lock_wanted(&self) -> Option<bool> {
        let relay = self.relay.as_ref()?;
        if self.relay_over() || !self.is_race_running() {
            return Some(false);
        }
        if !self.relay_live() {
            return match (relay.team_status, relay.role) {
                // A holder whose gates are open wants no lock whatever the
                // team status reads: a stale one must not strand it.
                (ParticipantStatus::Unknown, RelayRole::Holder) if !relay.gates_locked => {
                    Some(false)
                }
                (ParticipantStatus::Unknown, _) => None,
                _ => Some(false),
            };
        }
        match relay.role {
            RelayRole::Waiting => Some(true),
            RelayRole::Holder => Some(relay.gates_locked),
            RelayRole::Unknown => None,
        }
    }

    /// The runner waits for the baton in a relay being played.
    fn relay_waiting_live(&self) -> bool {
        self.relay_role() == Some(RelayRole::Waiting) && self.relay_live()
    }

    /// A locked waiting runner away from the Chapel, with no warp running
    /// or given up, past the gate window: the return to the Chapel may
    /// start (HP, which it needs, is the one thing left to check).
    fn relay_warp_may_start(&self, now: Instant) -> bool {
        self.relay_warp.is_none()
            && !self.relay_warp_given_up
            && self.relay_warp_landings < relay::WARP_LANDINGS_MAX
            && self.relay_lock == Some(true)
            && self.relay_asserted
            && self.relay_waiting_live()
            && self
                .frame_snapshot
                .map_id
                .is_some_and(|map| map != relay::CHAPEL_MAP_ID)
            && self.relay_lock_since.is_some_and(|since| {
                now.saturating_duration_since(since) >= relay::GATE_WINDOW
                    || self.last_loading_exit.is_some_and(|exit| exit > since)
            })
    }

    /// HP is read only while the return to the Chapel may start.
    fn relay_wants_hp(&self, now: Instant) -> bool {
        self.relay_warp_may_start(now)
    }

    /// Run a relay runner's lock, its return to the Chapel and its
    /// readiness, after `maintain_hunter`. Decided on the server's word and
    /// the machine's own writes; per frame a few comparisons while nothing
    /// changes. Every flag write waits until the player is loaded and
    /// `relay::SETTLE` has passed since the last loading exit, on the race
    /// save: a flag written during a load can be missed by the seed's
    /// events. A write the shell cannot make is silent: the value asked for
    /// is believed until the next loading exit asserts it again. No-op
    /// without a relay.
    fn maintain_relay(
        &mut self,
        connected: bool,
        loading_exit: bool,
        now: Instant,
        effects: &mut Vec<Effect>,
    ) {
        let Some(relay) = self.relay.as_ref() else {
            return;
        };
        crate::profile_span!("maintain_relay");
        let flags = relay.flags;
        let waiting_live = self.relay_waiting_live();
        let readable = self.frame_snapshot.position_readable;
        let map = self.frame_snapshot.map_id;
        if loading_exit {
            self.relay_asserted = false;
            self.relay_warp_given_up = false;
            // Where the load a warp started ended.
            if std::mem::take(&mut self.relay_landing_due) {
                if let Some(landed) = map.filter(|&m| m != relay::CHAPEL_MAP_ID) {
                    self.relay_warp_landings += 1;
                    warn!(
                        map = %format_map_id(landed),
                        landings = self.relay_warp_landings,
                        "[RELAY] Warp to the Chapel landed elsewhere"
                    );
                    if self.relay_warp_landings >= relay::WARP_LANDINGS_MAX {
                        self.set_status("Warp to the Chapel failed".to_string(), now);
                    }
                }
            }
        }
        if map == Some(relay::CHAPEL_MAP_ID) {
            self.relay_warp_landings = 0;
        }
        let settled = self
            .last_loading_exit
            .is_none_or(|at| now.saturating_duration_since(at) >= relay::SETTLE);
        let can_write = readable && !self.wrong_save && settled;

        // A warp ends with the waiting: a holder, a take or an over relay
        // does not go back. Its flag, still on, would warp the player the
        // next time the seed reads it.
        if !waiting_live {
            self.relay_warp_given_up = false;
            if let Some(mut warp) = self.relay_warp.take() {
                if let (Some(WarpStep::Lower(flag)), true) = (warp.abort(), can_write) {
                    effects.push(Effect::SetGameFlag {
                        flag_id: flag,
                        value: false,
                    });
                }
            }
        }

        if can_write {
            if let Some(want) = self.relay_lock_wanted() {
                if self.relay_lock != Some(want) {
                    let reason = if want {
                        if self.relay_role() == Some(RelayRole::Waiting) {
                            "waiting"
                        } else {
                            "cap"
                        }
                    } else if self.relay_over() {
                        "relay over"
                    } else if !self.is_race_running() {
                        "race not running"
                    } else if self.relay_live() {
                        "holder"
                    } else {
                        "relay not started"
                    };
                    if !want {
                        self.relay_warp_landings = 0;
                    }
                    info!(
                        reason,
                        "[RELAY] Lock {}",
                        if want { "raised" } else { "lowered" }
                    );
                    self.relay_lock_since = want.then_some(now);
                }
                if self.relay_lock != Some(want) || !self.relay_asserted {
                    effects.push(Effect::SetGameFlag {
                        flag_id: flags.lock_flag,
                        value: want,
                    });
                    self.relay_lock = Some(want);
                }
                self.relay_asserted = true;
            }

            if self.relay_cap_due {
                self.relay_cap_due = false;
                if self.relay_live() && self.relay_capped {
                    self.item_feed.push_banner(
                        FeedBanner {
                            icon: String::new(),
                            title: "QUOTA REACHED: PASS THE BATON".to_string(),
                            line: "Your gates are locked".to_string(),
                            detail: String::new(),
                            tone: FeedTone::Malus,
                        },
                        now,
                    );
                }
            }

            // Back to the Chapel once the lock has held the gates long
            // enough (or a load has come since), unless dead.
            if self.relay_warp_may_start(now) && self.frame_snapshot.hp.is_some_and(|hp| hp > 0) {
                self.relay_warp = Some(FlagWarp::new(flags.chapel_warp_flag));
            }
        }

        if let Some(warp) = self.relay_warp.as_mut() {
            // Never a flag write on an unsettled frame; an unloaded one
            // still ends the warp. Landed at the Chapel without a load
            // frame seen: it is over, its flag lowered if still on.
            let step = if map == Some(relay::CHAPEL_MAP_ID) {
                warp.abort().filter(|_| can_write)
            } else if !readable || can_write {
                warp.tick(readable, now)
            } else {
                None
            };
            let (flag, done) = (warp.flag(), warp.is_done());
            if done && step != Some(WarpStep::Failed) && map != Some(relay::CHAPEL_MAP_ID) {
                self.relay_landing_due = true;
            }
            match step {
                Some(WarpStep::Raise(flag)) => {
                    info!("[RELAY] Warp to the Chapel");
                    effects.push(Effect::SetGameFlag {
                        flag_id: flag,
                        value: true,
                    });
                }
                Some(WarpStep::Lower(flag)) => effects.push(Effect::SetGameFlag {
                    flag_id: flag,
                    value: false,
                }),
                Some(WarpStep::Failed) => {
                    warn!("[RELAY] Warp failed");
                    effects.push(Effect::SetGameFlag {
                        flag_id: flag,
                        value: false,
                    });
                    self.relay_warp_given_up = true;
                    self.set_status("Warp to the Chapel failed".to_string(), now);
                }
                None => {}
            }
            if done {
                self.relay_warp = None;
            }
        }

        if connected {
            let ready = waiting_live
                && self.relay_lock == Some(true)
                && self.relay_asserted
                && readable
                && !self.wrong_save
                && self.relay_warp.is_none()
                && self.frame_snapshot.map_id == Some(relay::CHAPEL_MAP_ID);
            if self.relay_ready_sent != Some(ready) {
                self.relay_ready_sent = Some(ready);
                effects.push(Effect::SendRelayReady { ready });
            }
        }

        self.maintain_relay_capture(connected, now, effects);
    }

    /// Ask the shell for the holder's state when one is wanted: a pending
    /// release first (given up `RELEASE_CAPTURE_TIMEOUT` after its receipt,
    /// or when the runner stops being the holder of a live relay), else the
    /// checkpoint of a zone just revealed. One capture at a time, on a
    /// connected frame with a readable position on the race save; a
    /// checkpoint that finds one in flight is dropped. Per frame: a few
    /// comparisons, and an allocation only when a capture is asked.
    fn maintain_relay_capture(&mut self, connected: bool, now: Instant, effects: &mut Vec<Effect>) {
        let holder = self.relay_holder_live();
        let checkpoint_due = std::mem::take(&mut self.relay_checkpoint_due);
        if let Some(pending) = &self.relay_release {
            if !holder {
                debug!(handoff_id = %pending.handoff_id, "[RELAY] Release dropped: no longer the holder");
                self.relay_release = None;
            } else if now >= pending.deadline {
                warn!(handoff_id = %pending.handoff_id, "[RELAY] Release not captured in time, dropped");
                self.relay_release = None;
                self.set_status("Handoff cancelled: not in game".to_string(), now);
            }
        }
        if !(connected
            && holder
            && self.frame_snapshot.position_readable
            && !self.wrong_save
            && self.relay_capture.is_none())
        {
            return;
        }
        let handoff_id = match &self.relay_release {
            Some(pending) => Some(pending.handoff_id.clone()),
            None if checkpoint_due => None,
            None => return,
        };
        crate::profile_span!("relay_capture_ask");
        self.relay_capture = Some(CaptureInFlight {
            handoff_id: handoff_id.clone(),
            link_lost: false,
        });
        effects.push(Effect::CaptureRelayState { handoff_id });
    }

    /// The shell's answer to `Effect::CaptureRelayState`: the captured state,
    /// or `None` when the game could not be read (a loading screen, a
    /// character not in the world). Returns the `relay_state` to send, or
    /// nothing: an unreadable release stays pending and is asked again on
    /// the next loaded frame until its time is up, an unreadable checkpoint
    /// is dropped, and a state is never sent stale (the socket dropped since
    /// the capture was asked, the runner no longer holds a live relay, the
    /// save is wrong, the release was replaced or timed out). Nothing is
    /// locked and no banner shows here: the server flips the role, and its
    /// `relay_update` decides.
    pub fn relay_state_captured(
        &mut self,
        handoff_id: Option<String>,
        state: Option<CharacterState>,
        now: Instant,
    ) -> Vec<Effect> {
        match &self.relay_capture {
            Some(asked) if asked.handoff_id == handoff_id => {}
            _ => {
                warn!(
                    ?handoff_id,
                    "[RELAY] Capture answer nobody asked for ignored"
                );
                return Vec::new();
            }
        }
        let asked = self.relay_capture.take().expect("checked above");
        let Some(mut state) = state else {
            debug!(?handoff_id, "[RELAY] State not readable");
            return Vec::new();
        };
        if asked.link_lost || !self.relay_holder_live() || self.wrong_save {
            debug!(?handoff_id, "[RELAY] Captured state not sent: stale");
            return Vec::new();
        }
        if let Some(id) = &handoff_id {
            match &self.relay_release {
                Some(pending) if pending.handoff_id == *id && now < pending.deadline => {}
                _ => {
                    debug!(handoff_id = %id, "[RELAY] Captured state not sent: release gone");
                    return Vec::new();
                }
            }
        }
        let cut = relay_items::fit_to_wire(&mut state);
        if cut > 0 {
            warn!(cut, "[RELAY] State over the wire caps, values cut");
        }
        info!(
            ?handoff_id,
            items = state.items.len(),
            graces = state.grace_flags.len(),
            "[RELAY] State captured"
        );
        if let Some(pending) = handoff_id.as_ref().and_then(|_| self.relay_release.take()) {
            self.relay_passed = Some((pending.to_name, now));
        }
        self.last_sent_debug = Some(format!("relay_state({handoff_id:?})"));
        vec![Effect::SendRelayState {
            handoff_id,
            state,
            igt_ms: self.effective_igt_ms(),
        }]
    }

    /// Send the pending event flags (never sent) with fresh message ids.
    fn send_pending_event_flags(&mut self, effects: &mut Vec<Effect>) {
        let pending: Vec<_> = self.flag_buffer.drain_pending().collect();
        for (flag_id, flag_igt) in pending {
            effects.push(self.queue_event_flag(flag_id, flag_igt));
            self.last_sent_debug = Some(format!("event_flag({}, igt={})", flag_id, flag_igt));
            info!(flag_id, "[RACE] Buffered event flag sent");
        }
    }

    /// Register an event flag as in-flight and return its send effect.
    fn queue_event_flag(&mut self, flag_id: u32, igt_ms: u32) -> Effect {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_event_flags
            .insert(message_id, BufferedEventFlag { flag_id, igt_ms });
        Effect::SendEventFlag {
            flag_id,
            igt_ms,
            message_id,
        }
    }

    /// Register a zone query as in-flight and return its send effect.
    fn queue_zone_query(
        &mut self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        quit_out: bool,
    ) -> Effect {
        let message_id = self.next_event_message_id;
        self.next_event_message_id = self.next_event_message_id.wrapping_add(1);
        self.in_flight_zone_queries.insert(
            message_id,
            BufferedZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id: map_id.clone(),
                position,
                play_region_id,
                quit_out,
            },
        );
        Effect::SendZoneQuery {
            igt_ms,
            message_id,
            grace_entity_id,
            map_id,
            position,
            play_region_id,
            quit_out,
        }
    }

    /// Replay in-flight event flags (sent but not yet ACKed) with their
    /// original `message_id`, preserving server-side idempotency.
    ///
    /// Entries stay in `in_flight_event_flags` after replay: they are only
    /// removed when the server sends `EventFlagAck` for each one.
    fn replay_in_flight_event_flags(&mut self, effects: &mut Vec<Effect>) {
        if self.in_flight_event_flags.is_empty() {
            return;
        }

        let mut entries: Vec<(u64, BufferedEventFlag)> = self
            .in_flight_event_flags
            .iter()
            .map(|(&k, &v)| (k, v))
            .collect();
        entries.sort_unstable_by_key(|(id, _)| *id);
        for (message_id, event) in entries {
            effects.push(Effect::SendEventFlag {
                flag_id: event.flag_id,
                igt_ms: event.igt_ms,
                message_id,
            });
            info!(
                message_id,
                flag_id = event.flag_id,
                "[RACE] Replaying in-flight event flag"
            );
        }
    }

    fn replay_in_flight_zone_queries(&mut self, effects: &mut Vec<Effect>) {
        if self.in_flight_zone_queries.is_empty() {
            return;
        }

        let mut message_ids: Vec<u64> = self.in_flight_zone_queries.keys().copied().collect();
        message_ids.sort_unstable();
        for message_id in message_ids {
            if let Some(zq) = self.in_flight_zone_queries.get(&message_id) {
                effects.push(Effect::SendZoneQuery {
                    igt_ms: zq.igt_ms,
                    message_id,
                    grace_entity_id: zq.grace_entity_id,
                    map_id: zq.map_id.clone(),
                    position: zq.position,
                    play_region_id: zq.play_region_id,
                    quit_out: zq.quit_out,
                });
                info!(message_id, "[RACE] Replaying in-flight zone query");
            }
        }
    }

    /// The single entry point of every arrival: local fog and finish
    /// captures (`record_capture`) and the server's arrivals at auth.
    /// Records `layer` at `igt_ms` only when it is deeper than every arrival
    /// recorded (a back-out or a revisit records nothing) and within
    /// `1..=total_layers`.
    ///
    /// The LiveSplit sync splits a timer it owns on a new arrival whatever
    /// `live` says, so no arrival may come from a wrong save. None does:
    /// flag polling and the loading-exit rescan stop while `wrong_save` is
    /// set. Any new caller must keep it that way.
    fn record_arrival(&mut self, layer: i32, igt_ms: u32) {
        let Ok(layer) = usize::try_from(layer) else {
            return;
        };
        if layer == 0
            || layer >= self.run_arrivals.len()
            || self.run_arrivals[layer..].iter().any(Option::is_some)
        {
            return;
        }
        info!(layer, igt_ms, "[RACE] New depth reached");
        self.run_arrivals[layer] = Some(igt_ms);
        self.run_view_changed = true;
    }

    /// A local fog or finish capture: records the depth it leads to while
    /// the run is live. A capture before the start, after the runner's
    /// finish or exit, or after the race is over is no arrival.
    fn record_capture(&mut self, flag_id: u32, igt_ms: u32, now: Instant) {
        if !self.run_live(now) {
            return;
        }
        let Some(seed) = self.race_state.seed.as_ref() else {
            return;
        };
        let layer = if self.finish_event == Some(flag_id) {
            Some(seed.total_layers)
        } else {
            seed.flag_layers.get(&flag_id).copied()
        };
        if let Some(layer) = layer {
            self.record_arrival(layer, igt_ms);
        }
    }

    /// A new attempt at the run: no depth reached yet.
    fn start_attempt(&mut self) {
        self.run_attempt = self.run_attempt.wrapping_add(1);
        self.run_arrivals.fill(None);
        self.run_view_changed = true;
        info!(attempt = self.run_attempt, "[RACE] New attempt at the run");
    }

    /// Appends a `LiveSplitRun` when the run's liveness, attempt or arrivals
    /// changed since the last one. Ends every `tick` and `handle_message`:
    /// an unchanged frame costs a few comparisons and allocates nothing.
    fn emit_run_view(&mut self, now: Instant, effects: &mut Vec<Effect>) {
        let Some(seed) = self.race_state.seed.as_ref() else {
            return;
        };
        // An old server sends no flag layers: LiveSplit is left alone.
        if seed.flag_layers.is_empty() {
            return;
        }
        let live = self.run_live(now);
        if live == self.run_view_live && !self.run_view_changed {
            return;
        }
        let view = RunView {
            live,
            attempt: self.run_attempt,
            fresh: self.run_arrivals.iter().all(Option::is_none),
            arrivals: self.run_arrivals.clone(),
            seed_number: seed.seed_number.clone(),
            category: seed.category.clone(),
        };
        self.run_view_live = live;
        self.run_view_changed = false;
        effects.push(Effect::LiveSplitRun(Box::new(view)));
    }
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ------------------------------------------------------------------
    // Harness
    // ------------------------------------------------------------------

    fn test_race(status: &str) -> RaceInfo {
        serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"Test Race","status":"{}"}}"#,
            status
        ))
        .unwrap()
    }

    fn test_seed(event_ids: &[u32], finish_event: Option<u32>, death_flags: &str) -> SeedInfo {
        let finish = finish_event
            .map(|f| f.to_string())
            .unwrap_or_else(|| "null".to_string());
        serde_json::from_str(&format!(
            r#"{{"total_layers": 3, "event_ids": {:?}, "finish_event": {}, "death_flags": {}}}"#,
            event_ids, finish, death_flags
        ))
        .unwrap()
    }

    fn test_participant(id: &str, status: &str, layer: i32) -> ParticipantInfo {
        serde_json::from_str(&format!(
            r#"{{"id":"{}","twitch_username":"u_{}","twitch_display_name":null,
                 "status":"{}","current_zone":null,"current_layer":{},
                 "igt_ms":0,"death_count":0}}"#,
            id, id, status, layer
        ))
        .unwrap()
    }

    fn auth_ok(status: &str, event_ids: &[u32], finish: Option<u32>) -> MachineMessage {
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed: test_seed(event_ids, finish, "{}"),
            participants: vec![test_participant("p1", "playing", 1)],
            phantom_skin: None,
            latest_mod_version: None,
            held_item: None,
            relay: None,
        }
    }

    /// Machine authed into a running race with regular flags [100, 200] and
    /// finish flag 900, `now` = machine birth time.
    fn running_machine(now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("running", &[100, 200, 900], Some(900)), now);
        m
    }

    /// Machine authed into a running DEATHLESS race, same shape as
    /// `running_machine` otherwise.
    fn deathless_running_machine(now: Instant) -> RaceMachine {
        deathless_machine("running", now)
    }

    fn deathless_machine(status: &str, now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo = serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"x","status":"{}","deathless":true}}"#,
            status
        ))
        .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        m
    }

    /// Machine authed into a running race with an IGT cutoff at 47:00, the
    /// local participant in `my_status`.
    fn cutoff_machine(my_status: &str, now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let race: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","igt_cutoff_ms":2820000}"#,
        )
        .unwrap();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", my_status, 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        m
    }

    #[test]
    fn igt_cutoff_counts_the_local_igt_down_in_whole_seconds() {
        let m = cutoff_machine("playing", Instant::now());
        assert_eq!(m.igt_cutoff_seconds_left(2_220_000), Some(600));
        // A partial second reads as the whole seconds below it, like the
        // wall-clock countdown.
        assert_eq!(m.igt_cutoff_seconds_left(2_819_001), Some(0));
        assert_eq!(m.igt_cutoff_seconds_left(2_830_000), Some(-10));
    }

    #[test]
    fn igt_cutoff_has_nothing_left_to_count_once_the_run_is_over() {
        // A finished run's IGT is frozen under the cutoff: no stale countdown.
        for status in ["finished", "abandoned", "disqualified"] {
            let m = cutoff_machine(status, Instant::now());
            assert_eq!(m.igt_cutoff_seconds_left(2_220_000), None, "{status}");
        }
    }

    #[test]
    fn a_race_without_an_igt_cutoff_counts_nothing() {
        // The race payload of a server older than protocol 1.8.
        let m = running_machine(Instant::now());
        assert_eq!(m.igt_cutoff_seconds_left(2_220_000), None);
    }

    fn snap_deaths(igt: Option<u32>, deaths: u32) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(deaths),
            position_readable: true,
            loading_screen: Some(false),
            ..FrameSnapshot::default()
        }
    }

    fn snap(igt: Option<u32>, pos: bool) -> FrameSnapshot {
        snap_load(igt, pos, Some(false))
    }

    fn snap_load(igt: Option<u32>, pos: bool, loading: Option<bool>) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(0),
            position_readable: pos,
            loading_screen: loading,
            ..FrameSnapshot::default()
        }
    }

    fn tick_in(
        snapshot: FrameSnapshot,
        connected: bool,
        reads: Option<Vec<(u32, bool)>>,
    ) -> TickInput {
        TickInput {
            snapshot,
            connected,
            warp_capture: None,
            position: None,
            flag_reads: reads,
            weapons: [None, None],
            flag_reader_ok: None,
        }
    }

    fn sent_flags(effects: &[Effect]) -> Vec<u32> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendEventFlag { flag_id, .. } => Some(*flag_id),
                _ => None,
            })
            .collect()
    }

    fn sent_message_ids(effects: &[Effect]) -> Vec<u64> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendEventFlag { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .collect()
    }

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    fn secs(v: u64) -> Duration {
        Duration::from_secs(v)
    }

    /// Captures tracing output for log assertions (scoped to the test thread
    /// via `tracing::subscriber::with_default`).
    #[derive(Clone, Default)]
    struct LogCapture(std::sync::Arc<std::sync::Mutex<Vec<u8>>>);

    impl LogCapture {
        fn contents(&self) -> String {
            String::from_utf8_lossy(&self.0.lock().unwrap()).into_owned()
        }
    }

    impl std::io::Write for LogCapture {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(buf);
            Ok(buf.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogCapture {
        type Writer = LogCapture;
        fn make_writer(&'a self) -> Self::Writer {
            self.clone()
        }
    }

    // ------------------------------------------------------------------
    // Quit-out detection latch
    // ------------------------------------------------------------------

    #[test]
    fn first_load_after_boot_does_not_arm() {
        // Mod injected while the player sits at the menu: the first IGT
        // observation has no prior reading to regress from.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.was_position_readable = false;
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(1000), false), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn death_reload_does_not_arm() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);

        // Death load: world reload, not save load. GameDataMan persists in
        // memory, so the IGT keeps its value through the loading screen.
        m.tick(tick_in(snap(Some(5_000), false), true, None), now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn igt_regression_around_unload_arms_latch() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);

        // Menu save-load: the reloaded save's IGT sits below the last
        // in-world observation (the on-disk save lags the in-memory IGT by
        // the post-flush fade).
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(8_500), false), true, None), now);
        assert!(m.pending_quit_out);

        // Full consumption at loading exit: penalty + tagged query.
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
    }

    #[test]
    fn igt_regression_on_loading_exit_frame_arms_and_consumes_same_tick() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);

        // The regressed IGT first becomes readable on the loading-exit frame
        // itself: arming must precede consumption within the same tick.
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert!(!m.pending_quit_out, "latch consumed in the same tick");
    }

    #[test]
    fn igt_regression_in_world_does_not_arm() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // Stable in-world frames: monotonic IGT, a frozen-clock frame (equal
        // value), then a hypothetical in-world regression. None may arm: the
        // first two are not strict regressions, and the last one happens
        // outside an unload context (both frames position-readable).
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);
        m.tick(tick_in(snap(Some(6_000), true), true, None), now);
        m.tick(tick_in(snap(Some(6_000), true), true, None), now);
        m.tick(tick_in(snap(Some(4_000), true), true, None), now);
        assert!(!m.pending_quit_out);
    }

    #[test]
    fn fog_traversal_with_deferred_flags_does_not_penalize() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(5_000), true), true, None), now);

        // Fog gate captured by the 10 Hz poll: cleared in memory and
        // deferred until loading exit.
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(5_100), true), true, Some(vec![(100, true)])),
            later,
        );
        // Cross-map load: world reload, not save load, so the IGT stays
        // monotonic through the loading screen.
        m.tick(tick_in(snap(Some(5_200), false), true, None), later);
        let mut input = tick_in(snap(Some(5_300), true), true, None);
        input.flag_reads = Some(vec![]);
        let fx = m.tick(input, later);
        assert_eq!(penalty_ms(&fx), None);
        assert!(sent_flags(&fx).contains(&100), "deferred flag sent at exit");
        assert_eq!(
            sent_zone_query_quit_out(&fx),
            None,
            "fog exit sends event flags, not a zone query"
        );
    }

    // ------------------------------------------------------------------
    // Wrong-save freeze
    // ------------------------------------------------------------------

    /// In-world at 10_000ms, then a reload that lands at `reload_igt`.
    fn reload_to(m: &mut RaceMachine, reload_igt: u32, now: Instant) {
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(reload_igt), false), true, None), now);
    }

    #[test]
    fn held_igt_bridges_a_menu_reload() {
        let now = Instant::now();
        let mut m = running_machine(now);
        assert_eq!(m.held_igt_ms(Some(0)), None);
        m.tick(tick_in(snap(Some(2_220_000), true), true, None), now);
        assert_eq!(m.held_igt_ms(Some(0)), Some(2_220_000));
        assert_eq!(m.held_igt_ms(None), Some(2_220_000));
        assert_eq!(m.held_igt_ms(Some(2_221_000)), Some(2_221_000));
    }

    #[test]
    fn held_igt_keeps_the_race_save_through_a_wrong_save_reload() {
        // A menu reload out of a wrong save holds the race save's IGT, not
        // the wrong save's.
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 7_200_000, now);
        assert!(m.wrong_save);
        assert_eq!(m.held_igt_ms(Some(0)), Some(10_000));
    }

    #[test]
    fn display_igt_holds_only_a_playing_runners_clock() {
        // Still ready at the start, in the world on an old save, then off to
        // the title for a New Game: the old save's IGT is no race clock.
        let now = Instant::now();
        let mut m = cutoff_machine("ready", now);
        m.tick(tick_in(snap(Some(2_832_000), true), true, None), now);
        assert_eq!(m.display_igt_ms(None), None);
        assert_eq!(m.display_igt_ms(Some(0)), None);
        assert_eq!(m.display_igt_ms(Some(5_000)), Some(5_000));

        let mut m = cutoff_machine("playing", now);
        m.tick(tick_in(snap(Some(2_832_000), true), true, None), now);
        assert_eq!(m.display_igt_ms(None), Some(2_832_000));
    }

    #[test]
    fn forward_jump_across_unload_freezes() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 7_200_000, now);
        assert!(m.wrong_save);
        assert!(!m.pending_quit_out, "no penalty into a foreign save");

        // Frozen: a loading exit produces no sends and no game writes.
        let mut input = tick_in(snap(Some(7_200_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert!(fx.is_empty(), "frozen machine emits nothing, got {fx:?}");

        // Frozen: no periodic status updates either.
        let fx = m.tick(
            tick_in(snap(Some(7_205_000), true), true, None),
            now + secs(5),
        );
        assert!(fx
            .iter()
            .all(|e| !matches!(e, Effect::SendStatusUpdate { .. })));
        assert!(!m.wants_status_update(now + secs(5), 7_205_000));
        assert!(!m.wants_flag_reads(FrameNeeds::default(), true, true));
    }

    #[test]
    fn same_save_reload_does_not_freeze() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 8_500, now); // ordinary quit-out
        assert!(!m.wrong_save);
        assert!(m.pending_quit_out);
    }

    #[test]
    fn wrong_save_recovers_when_race_save_returns() {
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 7_200_000, now);
        assert!(m.wrong_save);

        // Player keeps playing the wrong save: still frozen.
        m.tick(
            tick_in(snap(Some(7_260_000), true), true, None),
            now + secs(60),
        );
        assert!(m.wrong_save);

        // Reload back into the race save: inside the plausible window of
        // the last good observation (10_000 + elapsed + slack).
        m.tick(tick_in(snap(None, false), true, None), now + secs(90));
        m.tick(
            tick_in(snap(Some(9_000), false), true, None),
            now + secs(90),
        );
        assert!(!m.wrong_save, "race save back, freeze lifted");
        assert!(
            !m.pending_quit_out,
            "the corrective reload is a forward jump from the wrong save, not a quit-out"
        );

        // Life resumes: a loading exit sends again.
        let mut input = tick_in(snap(Some(9_100), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now + secs(90));
        assert!(fx.iter().any(|e| matches!(e, Effect::SendZoneQuery { .. })));
    }

    #[test]
    fn wrong_save_reload_does_not_flush_buffers() {
        // Buffers parked before the wrong-save reload must survive the
        // freeze AND the recovery reload (both would previously flush).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), false, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(10_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(10_200), false), false, None), later);
        let mut input = tick_in(snap(Some(10_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        // Wrong save loaded, then the race save comes back.
        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(tick_in(snap(Some(7_200_000), false), false, None), later);
        assert!(m.wrong_save);
        m.tick(tick_in(snap(None, false), false, None), later + secs(30));
        m.tick(
            tick_in(snap(Some(10_300), false), false, None),
            later + secs(30),
        );
        assert!(!m.wrong_save);
        assert!(
            m.flag_buffer.has_pending(),
            "parked traversal survives the whole wrong-save episode"
        );
    }

    #[test]
    fn wrong_save_recovery_requires_elapsed_real_time() {
        // The recovery window is `[last_good - SAVE_RELOAD_IGT_DROP_MS,
        // last_good + elapsed_wall + WRONG_SAVE_RECOVERY_SLACK_MS]`: an IGT
        // just past the fixed slack must wait for enough real time to pass
        // before it becomes plausible again.
        let now = Instant::now();
        let mut m = running_machine(now);
        reload_to(&mut m, 200_000, now);
        assert!(m.wrong_save);

        // 25_000 is beyond the fixed window (10_000 + 10_000 slack) right
        // after the freeze: not enough elapsed time to explain it yet.
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(25_000), false), true, None), now);
        assert!(m.wrong_save, "not enough elapsed time to explain this IGT");

        // After 60s of real time the same IGT is plausible again: the
        // elapsed term widens the window and the freeze lifts.
        m.tick(tick_in(snap(None, false), true, None), now + secs(60));
        m.tick(
            tick_in(snap(Some(25_000), false), true, None),
            now + secs(60),
        );
        assert!(
            !m.wrong_save,
            "elapsed real time makes 25_000 plausible now"
        );
    }

    #[test]
    fn forward_jump_at_exact_slack_boundary_does_not_freeze() {
        // Exactly WRONG_SAVE_FORWARD_SLACK_MS forward of the last good IGT:
        // the strict `>` in forward_jump means this is ordinary progress,
        // not a wrong save.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(
            tick_in(
                snap(Some(10_000 + WRONG_SAVE_FORWARD_SLACK_MS), false),
                true,
                None,
            ),
            now,
        );
        assert!(!m.wrong_save, "exact boundary is not a forward jump");
    }

    #[test]
    fn race_start_clears_pre_start_wrong_save_freeze() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        // Wrong 2h save loaded by mistake during setup: freezes.
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(!m.wrong_save, "race start clears a stale pre-start freeze");

        // Fresh race save (IGT near 0), past the countdown: normal life,
        // no freeze, no penalty, sends work.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(1_000), true), true, None),
            after_countdown,
        );
        m.tick(tick_in(snap(None, false), true, None), after_countdown);
        let mut input = tick_in(snap(Some(1_000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert!(!m.wrong_save);
        assert_eq!(penalty_ms(&fx), None);
        assert!(fx.iter().any(|e| matches!(e, Effect::SendZoneQuery { .. })));
    }

    // ------------------------------------------------------------------
    // Message handling basics
    // ------------------------------------------------------------------

    #[test]
    fn test_race_start_sets_running_and_countdown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let fx = m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        assert!(fx.is_empty());
        assert!(m.is_race_setup());

        let fx = m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(fx.is_empty());
        assert!(m.is_race_running());
        assert!(m.is_countdown_active(now));
        assert!(!m.is_countdown_active(now + secs(4)));
    }

    // ------------------------------------------------------------------
    // Flag lifecycle scenarios
    // ------------------------------------------------------------------

    #[test]
    fn test_defer_then_drain_at_loading_exit() {
        let now = Instant::now();
        let mut m = running_machine(now);

        // Regular flag set during the 10Hz poll: cleared in game + deferred,
        // NOT sent yet.
        let t1 = now + ms(150);
        let fx = m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            t1,
        );
        assert!(sent_flags(&fx).is_empty(), "no send before loading exit");
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 100,
            value: false
        }));
        assert!(m.flag_buffer.has_deferred());
        // Regular flags are not tracked in triggered_flags
        assert!(!m.triggered_flags.contains(&100));

        // Loading screen (position unreadable), then exit: deferred flag sent.
        let t2 = t1 + ms(50);
        m.tick(tick_in(snap(Some(1200), false), true, None), t2);
        let t3 = t2 + ms(30);
        let fx = m.tick(
            tick_in(
                snap(Some(1300), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            t3,
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        assert!(!m.flag_buffer.has_deferred());
        assert_eq!(m.in_flight_event_flags.len(), 1);

        // Second identical poll read: nothing new (flag cleared in memory
        // would read false; even a stale true defers again by design).
        let t4 = t3 + ms(150);
        let fx = m.tick(
            tick_in(
                snap(Some(1500), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            t4,
        );
        assert!(sent_flags(&fx).is_empty());
    }

    #[test]
    fn test_finish_flag_sends_immediately() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // First tick marks ready_sent (SendReady fires once).
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        // Sent in the SAME tick, no defer, no game-memory clear for finish.
        assert_eq!(sent_flags(&fx), vec![900]);
        assert!(m.triggered_flags.contains(&900));
        assert!(!fx
            .iter()
            .any(|e| matches!(e, Effect::SetGameFlag { flag_id: 900, .. })));
    }

    #[test]
    fn test_finish_flag_pending_when_gated_then_flushed_on_reconnect() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(MachineMessage::RaceStart(10), now);

        // Finish flag during countdown: buffered pending, no send.
        let fx = m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(m.triggered_flags.contains(&900));

        // Reconnect after the countdown: pending drained.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(11),
        );
        let fx = m.tick(
            tick_in(snap(Some(20_000), true), true, Some(vec![])),
            now + secs(12),
        );
        assert_eq!(sent_flags(&fx), vec![900]);
    }

    #[test]
    fn test_park_and_replay_on_reconnect_with_requeue() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Defer a regular flag, then lose the connection: parked to pending.
        m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        let fx = m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(200),
        );
        assert!(fx.is_empty());
        assert!(!m.flag_buffer.has_deferred(), "deferred parked to pending");

        // Reconnected: pending drained with a fresh message_id.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + ms(300),
        );
        let fx = m.tick(
            tick_in(snap(Some(2000), true), true, Some(vec![])),
            now + ms(350),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        let first_id = sent_message_ids(&fx)[0];
        assert!(m.in_flight_event_flags.contains_key(&first_id));

        // Server reports the message never left the socket: requeued.
        m.handle_message(
            MachineMessage::RequeueEventFlag {
                flag_id: 100,
                igt_ms: 1000,
                message_id: first_id,
            },
            now + ms(400),
        );
        assert!(!m.in_flight_event_flags.contains_key(&first_id));

        // Next reconnect drains it again with a NEW, larger message_id.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + ms(500),
        );
        let fx = m.tick(
            tick_in(snap(Some(3000), true), true, Some(vec![])),
            now + ms(550),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        let second_id = sent_message_ids(&fx)[0];
        assert!(second_id > first_id, "message ids stay monotonic");
    }

    #[test]
    fn test_save_reload_purges_per_save_state() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Capture a finish flag and defer a regular one.
        m.tick(
            tick_in(
                snap(Some(100_000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // IGT regression = save reload: per-save state cleared, no sends.
        let fx = m.tick(tick_in(snap(Some(1_000), true), true, None), now + ms(200));
        assert!(sent_flags(&fx).is_empty());
        assert!(m.triggered_flags.is_empty());
        assert!(!m.flag_buffer.has_deferred());
    }

    #[test]
    fn a_solo_reset_reconnect_tracks_the_new_character() {
        // A Set Seed solo reset drops the connection with 1000 (not
        // permanent): the mod reconnects, gets auth_ok and race_start again
        // (a solo run starts on connection), and a player who kept the game
        // running leaves the old save for a New Game. A finish the old save
        // latched (one the server dropped) must not block the new
        // character's, and the switch from a long run reads as neither a
        // quit-out nor a wrong save.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(MachineMessage::RaceStart(0), now);
        m.tick(
            tick_in(snap(Some(1_799_000), true), true, None),
            now + ms(10),
        );
        let fx = m.tick(
            tick_in(
                snap(Some(1_800_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        assert_eq!(sent_flags(&fx), vec![900]);
        let message_id = sent_message_ids(&fx)[0];
        m.handle_message(MachineMessage::EventFlagAck { message_id }, now + ms(200));

        let reset = now + secs(5);
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            reset,
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            reset + ms(500),
        );
        m.handle_message(
            auth_ok("running", &[100, 200, 900], Some(900)),
            reset + ms(600),
        );
        m.handle_message(MachineMessage::RaceStart(0), reset + ms(600));
        // Still in the old save for a moment, then the main menu.
        m.tick(
            tick_in(snap(Some(1_801_000), true), true, None),
            reset + secs(1),
        );
        m.tick(tick_in(snap(None, false), true, None), reset + secs(10));

        // New Game.
        let fx = m.tick(tick_in(snap(Some(300), true), true, None), reset + secs(40));
        assert!(!m.wrong_save);
        assert_eq!(penalty_ms(&fx), None);
        assert!(m.triggered_flags.is_empty());

        // The new character's finish goes out.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            reset + secs(100),
        );
        assert_eq!(sent_flags(&fx), vec![900]);
    }

    // ------------------------------------------------------------------
    // Zone reveal scenarios
    // ------------------------------------------------------------------

    fn zone_update(name: &str, message_id: Option<u64>) -> MachineMessage {
        MachineMessage::ZoneUpdate {
            node_id: "n1".to_string(),
            display_name: name.to_string(),
            tier: Some(2),
            original_tier: Some(2),
            layer: Some(2),
            is_first_visit: true,
            exits: Vec::new(),
            unused_exits: None,
            defeat_flag: None,
            message_id,
        }
    }

    #[test]
    fn test_zone_reveal_waits_for_loading_end() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Stormveil", None), now + ms(100));
        assert!(m.pending_zone_update.is_some());
        assert_eq!(m.zone_version, 0, "no bump before reveal");

        // Still loading: byte set, position unreadable.
        m.tick(
            tick_in(snap_load(Some(1000), false, Some(true)), true, None),
            now + ms(200),
        );
        assert!(m.race_state.current_zone.is_none());

        // World loaded (position readable) but the loading screen still
        // displayed (byte set): not revealed.
        m.tick(
            tick_in(snap_load(Some(1200), true, Some(true)), true, Some(vec![])),
            now + ms(300),
        );
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, None),
            now + secs(3),
        );
        assert!(m.race_state.current_zone.is_none());

        // Byte clear: revealed on that very frame.
        m.tick(
            tick_in(snap_load(Some(2100), true, Some(false)), true, None),
            now + secs(4),
        );
        let zone = m.race_state.current_zone.as_ref().expect("revealed");
        assert_eq!(zone.display_name, "Stormveil");
        assert!(m.pending_zone_update.is_none());
        assert_eq!(m.zone_version, 1, "reveal bumps the render-cache key");
    }

    #[test]
    fn test_zone_reveal_uses_direct_screen_signal() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Stormveil", None), now + ms(100));

        // Menu system says loading screen: not revealed, even though the
        // legacy world-clock byte already reads clear (the direct signal
        // wins when present).
        let mut s = snap_load(Some(1_000), true, Some(false));
        s.screen_in_game = Some(false);
        s.blackscreen = Some(false);
        m.tick(tick_in(s, true, Some(vec![])), now + ms(200));
        assert!(m.race_state.current_zone.is_none());

        // In game but still under the fade: the player cannot see the
        // world yet, so the destination is not revealed either.
        let mut s = snap_load(Some(1_100), true, Some(false));
        s.screen_in_game = Some(true);
        s.blackscreen = Some(true);
        m.tick(tick_in(s, true, None), now + ms(300));
        assert!(m.race_state.current_zone.is_none());

        // Fade lifted: revealed on that frame.
        let mut s = snap_load(Some(1_200), true, Some(false));
        s.screen_in_game = Some(true);
        s.blackscreen = Some(false);
        m.tick(tick_in(s, true, None), now + ms(400));
        assert_eq!(
            m.race_state
                .current_zone
                .as_ref()
                .map(|z| z.display_name.as_str()),
            Some("Stormveil")
        );
    }

    #[test]
    fn test_zone_reveal_timeout_when_byte_stuck() {
        // Frozen-clock event seeds (weather plugin FreezeTime): the byte
        // never clears, the defensive timeout bounds the wait.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Volcano Manor", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), true, Some(true)), true, None),
            now + ms(200),
        );
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT - ms(50),
        );
        assert!(
            m.race_state.current_zone.is_none(),
            "byte stuck: no reveal before the timeout"
        );

        m.tick(
            tick_in(snap_load(Some(3000), true, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT + ms(50),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Volcano Manor"
        );
    }

    #[test]
    fn test_zone_reveal_timeout_still_requires_position() {
        // The timeout path never reveals while the world is not loaded: a
        // long load on a frozen-clock seed reveals at loading exit, not
        // mid-load.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Leyndell", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), false, Some(true)), true, None),
            now + ZONE_REVEAL_TIMEOUT + secs(3),
        );
        assert!(
            m.race_state.current_zone.is_none(),
            "position unreadable: no reveal even past the timeout"
        );

        // Position becomes readable (timeout long elapsed): reveal fires
        // even though the byte is still stuck.
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(true)), true, Some(vec![])),
            now + ZONE_REVEAL_TIMEOUT + secs(4),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Leyndell"
        );
    }

    #[test]
    fn test_zone_reveal_byte_unreadable_counts_as_done() {
        // Byte unreadable (game patch moved it, pointer chain broken):
        // position readability alone gates the reveal, as before 1ddfe1c6.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(zone_update("Siofra", None), now);

        m.tick(
            tick_in(snap_load(Some(1000), false, None), true, None),
            now + ms(200),
        );
        assert!(m.race_state.current_zone.is_none(), "position still gates");

        m.tick(
            tick_in(snap_load(Some(2000), true, None), true, Some(vec![])),
            now + ms(400),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Siofra"
        );
    }

    #[test]
    fn test_zone_reveal_instant_on_reconnect_resend() {
        // Reconnect scenario (WEBSOCKET_LIFECYCLE.md): the server resends
        // the zone_update while the player stands in a loaded world (byte
        // clear, position readable): the reveal fires on the next tick.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(1000), true), true, None), now + ms(10));

        m.handle_message(zone_update("Caelid", None), now + secs(10));
        m.tick(
            tick_in(snap(Some(2000), true), true, None),
            now + secs(10) + ms(20),
        );
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().display_name,
            "Caelid"
        );
    }

    #[test]
    fn test_zone_reveal_stall_warns_once() {
        let logs = LogCapture::default();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(logs.clone())
            .with_max_level(tracing::Level::WARN)
            .with_ansi(false)
            .finish();
        let warn_count = |l: &LogCapture| l.contents().matches("Zone reveal still pending").count();

        tracing::subscriber::with_default(subscriber, || {
            let now = Instant::now();
            let mut m = running_machine(now);
            m.handle_message(zone_update("Farum Azula", None), now);

            // Position readability broken: unreadable the whole time, so
            // neither the byte path nor the timeout path can reveal.
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(29),
            );
            assert!(m.race_state.current_zone.is_none());
            assert_eq!(warn_count(&logs), 0, "no stall warn before the threshold");

            // Crossing the threshold: exactly one warn, still no reveal.
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(31),
            );
            assert_eq!(warn_count(&logs), 1, "one stall warn past the threshold");
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(40),
            );
            assert_eq!(
                warn_count(&logs),
                1,
                "stall warn fires once per pending zone"
            );
            assert!(
                m.race_state.current_zone.is_none(),
                "diagnostic only, no reveal while position is unreadable"
            );

            // A new zone_update re-arms the warn, and last-writer-wins
            // re-anchors the stall clock on the latest arrival.
            m.handle_message(zone_update("Liurnia", None), now + secs(41));
            m.handle_message(zone_update("Altus", None), now + secs(50));
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(75),
            );
            assert_eq!(
                warn_count(&logs),
                1,
                "stall clock re-anchored on the latest zone_update"
            );
            m.tick(
                tick_in(snap_load(Some(1000), false, Some(true)), true, None),
                now + secs(81),
            );
            assert_eq!(warn_count(&logs), 2, "second pending zone warns again");
        });
    }

    #[test]
    fn test_pre_reveal_layer_freezes_until_reveal() {
        let now = Instant::now();
        let mut m = running_machine(now);
        assert_eq!(m.my_participant().unwrap().current_layer, 1);

        // Zone update pending + leaderboard bumps my layer: old layer frozen.
        m.handle_message(zone_update("Caelid", None), now + ms(100));
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "playing", 2)],
                leader_splits: None,
            },
            now + ms(150),
        );
        assert_eq!(m.pre_reveal_layer, Some(1));

        // Still loading (byte set): frozen until the reveal.
        m.tick(
            tick_in(snap_load(Some(1200), true, Some(true)), true, Some(vec![])),
            now + ms(300),
        );
        assert_eq!(m.pre_reveal_layer, Some(1), "frozen until reveal");
        m.tick(
            tick_in(snap_load(Some(2000), true, Some(false)), true, None),
            now + ms(400),
        );
        assert!(m.pre_reveal_layer.is_none());
    }

    // ------------------------------------------------------------------
    // Race lifecycle scenarios
    // ------------------------------------------------------------------

    #[test]
    fn test_frozen_igt_on_race_end_and_reset_on_auth() {
        let now = Instant::now();
        let mut m = running_machine(now);

        // Race ends while I am still playing: IGT frozen from the shell read.
        m.handle_message(
            MachineMessage::RaceStatusChange {
                status: RaceStatus::Finished,
                current_igt: Some(4242),
            },
            now + secs(60),
        );
        assert_eq!(m.frozen_igt_ms, Some(4242));
        assert_eq!(m.frame_snapshot.igt_ms, Some(4242));

        // Reconnect resets the freeze.
        m.handle_message(auth_ok("running", &[100], Some(900)), now + secs(61));
        assert!(m.frozen_igt_ms.is_none());
    }

    #[test]
    fn race_end_during_a_menu_reload_freezes_the_last_good_igt() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(4242), true), true, None), now);
        m.handle_message(
            MachineMessage::RaceStatusChange {
                status: RaceStatus::Finished,
                current_igt: Some(0),
            },
            now + secs(60),
        );
        assert_eq!(m.frozen_igt_ms, Some(4242));
    }

    #[test]
    fn test_countdown_gates_loading_exit_sends() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        m.handle_message(MachineMessage::RaceStart(10), now + ms(20));

        // Defer a flag during countdown.
        m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert!(m.flag_buffer.has_deferred());

        // Loading exit during countdown: nothing sent, deferred parked.
        m.tick(tick_in(snap(Some(1100), false), true, None), now + ms(200));
        let fx = m.tick(
            tick_in(snap(Some(1200), true), true, Some(vec![])),
            now + ms(250),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(!m.flag_buffer.has_deferred(), "parked to pending");
    }

    #[test]
    fn test_ack_idempotence() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Unknown ack: no state change, no panic.
        let fx = m.handle_message(MachineMessage::EventFlagAck { message_id: 999 }, now);
        assert!(fx.is_empty());

        // Send a finish flag, then ack it: removed from in-flight.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + ms(150),
        );
        let id = sent_message_ids(&fx)[0];
        assert!(m.in_flight_event_flags.contains_key(&id));
        m.handle_message(MachineMessage::EventFlagAck { message_id: id }, now);
        assert!(!m.in_flight_event_flags.contains_key(&id));
    }

    #[test]
    fn test_status_update_cadence_and_gating() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let has_status = |fx: &[Effect]| {
            fx.iter()
                .any(|e| matches!(e, Effect::SendStatusUpdate { .. }))
        };

        // 1.2s after birth: fires.
        let fx = m.tick(tick_in(snap(Some(5000), true), true, None), now + ms(1200));
        assert!(has_status(&fx));

        // 200ms later: throttled.
        let fx = m.tick(tick_in(snap(Some(5200), true), true, None), now + ms(1400));
        assert!(!has_status(&fx));

        // Another second later: fires again.
        let fx = m.tick(tick_in(snap(Some(6300), true), true, None), now + ms(2400));
        assert!(has_status(&fx));

        // IGT 0 (quit-out): skipped.
        let fx = m.tick(tick_in(snap(Some(0), true), true, None), now + ms(3600));
        assert!(!has_status(&fx));

        // Once I am finished: skipped.
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "finished", 3)],
                leader_splits: None,
            },
            now + ms(3700),
        );
        let fx = m.tick(tick_in(snap(Some(9000), true), true, None), now + ms(4800));
        assert!(!has_status(&fx));
    }

    #[test]
    fn test_death_counts_emit_threshold_flags() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: test_race("running"),
                seed: test_seed(&[100], None, r#"{"zone_a": [10, 11, 12]}"#),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );

        let mut counts = HashMap::new();
        counts.insert("zone_a".to_string(), 4u32);
        let fx = m.handle_message(MachineMessage::DeathCounts(counts), now);
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 10,
            value: true
        }));
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 11,
            value: true
        }));
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 12,
            value: false
        }));
        assert_eq!(m.race_state.death_counts.get("zone_a"), Some(&4));
    }

    // ------------------------------------------------------------------
    // Quit-out consumption (penalty + tagged zone query)
    // ------------------------------------------------------------------

    fn sent_zone_query_quit_out(effects: &[Effect]) -> Option<bool> {
        effects.iter().find_map(|e| match e {
            Effect::SendZoneQuery { quit_out, .. } => Some(*quit_out),
            _ => None,
        })
    }

    fn penalty_ms(effects: &[Effect]) -> Option<u32> {
        effects.iter().find_map(|e| match e {
            Effect::ApplyIgtPenalty { ms } => Some(*ms),
            _ => None,
        })
    }

    /// Full quit-out cycle: in-world -> menu -> reload with a regressed IGT.
    /// Returns the loading-exit effects.
    fn quit_out_cycle(m: &mut RaceMachine, now: Instant) -> Vec<Effect> {
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        let mut input = tick_in(snap(Some(8_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: Some(6100),
        });
        m.tick(input, now)
    }

    #[test]
    fn quit_out_cycle_applies_penalty_banner_and_tagged_query() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx = quit_out_cycle(&mut m, now);

        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert_eq!(m.get_status(now), Some("Quit-out: +2s"));
        assert!(!m.pending_quit_out, "latch consumed");
    }

    #[test]
    fn quit_out_penalty_pulls_status_update_forward() {
        let now = Instant::now();
        let mut m = running_machine(now);
        quit_out_cycle(&mut m, now);

        // Immediately after the reload tick, a status_update fires without
        // waiting for the periodic 1s gate.
        let fx = m.tick(tick_in(snap(Some(5000), true), true, None), now + ms(50));
        assert!(fx
            .iter()
            .any(|e| matches!(e, Effect::SendStatusUpdate { .. })));
    }

    #[test]
    fn quit_out_custom_and_zero_penalty() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":5000}"#,
        )
        .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), Some(5000));
        assert_eq!(m.get_status(now), Some("Quit-out: +5s"));

        // penalty 0: no penalty effect, no banner, query still tagged.
        let mut m0 = RaceMachine::new(1, String::new(), false, now);
        let mut race0: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":0}"#,
        )
        .unwrap();
        race0.reparse_dates();
        m0.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: race0,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m0, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(m0.get_status(now), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));

        // Non-round-thousand penalty: banner keeps the decimal instead of
        // truncating to "+0s"/"+1s".
        let mut m1 = RaceMachine::new(1, String::new(), false, now);
        let mut race1: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":1500}"#,
        )
        .unwrap();
        race1.reparse_dates();
        m1.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: race1,
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m1, now);
        assert_eq!(penalty_ms(&fx), Some(1500));
        assert_eq!(m1.get_status(now), Some("Quit-out: +1.5s"));
    }

    #[test]
    fn no_penalty_when_not_running_or_finished() {
        let now = Instant::now();

        // Race in setup.
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), None, "setup: no query sent");

        // Finished participant.
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race: test_race("running"),
                seed: test_seed(&[100], Some(900), "{}"),
                participants: vec![test_participant("p1", "finished", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), None);
    }

    #[test]
    fn training_quit_out_applies_penalty() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), true, now);
        m.handle_message(auth_ok("running", &[100], Some(900)), now);
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
        assert_eq!(m.get_status(now), Some("Quit-out: +2s"));
    }

    #[test]
    fn large_regression_is_restore_not_quit_out() {
        // A backup restore rolls the IGT back by minutes: no penalty is
        // armed (the flush path is covered by the boundary and purge tests).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(600_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(500_000), false), true, None), now);
        assert!(!m.pending_quit_out, "restore must not arm the penalty");
    }

    #[test]
    fn boundary_regression_is_rollback_not_quit_out() {
        // Regression of exactly SAVE_RELOAD_IGT_DROP_MS: rollback
        // semantics win. The per-save flush fires (pending cleared) and
        // no penalty is armed; flush and penalty are mutually exclusive.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(100_000), true), true, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(100_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(100_200), false), false, None), later);
        let mut input = tick_in(snap(Some(100_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(
            tick_in(snap(Some(100_300 - 60_000), false), false, None),
            later,
        );
        assert!(!m.pending_quit_out, "boundary regression must not arm");
        assert!(
            !m.flag_buffer.has_pending(),
            "boundary regression flushes per-save state"
        );
    }

    /// Snapshot with the direct screen signal present (in game), fade state
    /// per `blackscreen`.
    fn snap_black(igt: Option<u32>, pos: bool, blackscreen: bool) -> FrameSnapshot {
        FrameSnapshot {
            igt_ms: igt,
            death_count: Some(0),
            position_readable: pos,
            loading_screen: Some(false),
            screen_in_game: Some(true),
            blackscreen: Some(blackscreen),
            ..FrameSnapshot::default()
        }
    }

    #[test]
    fn test_blackscreen_freeze_holds_and_advances_baseline() {
        let now = Instant::now();
        let mut m = running_machine(now);

        // Clear frame seeds the baseline.
        m.tick(
            tick_in(snap_black(Some(100_000), true, false), true, None),
            now,
        );
        assert_eq!(m.freeze_last_igt, Some(100_000));

        // Fade frames: the game-side creep is written back every frame and
        // the machine itself sees the frozen value.
        for i in 1..=3u64 {
            let fx = m.tick(
                tick_in(snap_black(Some(100_016), true, true), true, None),
                now + ms(16 * i),
            );
            assert!(fx.contains(&Effect::FreezeIgt { ms: 100_000 }));
            assert_eq!(m.frame_snapshot.igt_ms, Some(100_000));
        }

        // Fade over: baseline advances again, no more freeze writes.
        let fx = m.tick(
            tick_in(snap_black(Some(100_100), true, false), true, None),
            now + ms(100),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));
        assert_eq!(m.freeze_last_igt, Some(100_100));
    }

    #[test]
    fn test_freeze_reseeds_on_large_jump() {
        // A jump of BLACKSCREEN_FREEZE_MAX_STEP_MS or more during a fade is
        // a legitimate discontinuity (save load): do not fight it.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(
            tick_in(snap_black(Some(100_000), true, false), true, None),
            now,
        );
        let fx = m.tick(
            tick_in(snap_black(Some(101_000), true, true), true, None),
            now + ms(16),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));
        assert_eq!(m.freeze_last_igt, Some(101_000));
    }

    #[test]
    fn test_freeze_gate_closed_outside_running_race_and_countdown() {
        let now = Instant::now();
        // Race in setup: no freeze.
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        m.tick(
            tick_in(snap_black(Some(1_000), true, false), true, None),
            now,
        );
        let fx = m.tick(
            tick_in(snap_black(Some(1_016), true, true), true, None),
            now + ms(16),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));

        // Countdown: no freeze either.
        let mut m = running_machine(now);
        m.handle_message(MachineMessage::RaceStart(10), now);
        m.tick(
            tick_in(snap_black(Some(1_000), true, false), true, None),
            now + ms(20),
        );
        let fx = m.tick(
            tick_in(snap_black(Some(1_016), true, true), true, None),
            now + ms(40),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));
    }

    #[test]
    fn test_freeze_writeback_never_arms_quit_out() {
        // The write-back makes the raw game IGT sawtooth (creep up, get
        // pulled back). Because the freeze block runs before the
        // reload/quit-out block and overrides the snapshot, the machine
        // must never read those pull-backs as an IGT regression, even
        // with position unreadable (fade context).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(
            tick_in(snap_black(Some(100_000), true, false), true, None),
            now,
        );
        // Raw reads during the fade: 100_033 then 100_016 (below the
        // previous raw read, exactly the sawtooth a per-frame write-back
        // produces).
        m.tick(
            tick_in(snap_black(Some(100_033), false, true), true, None),
            now + ms(16),
        );
        m.tick(
            tick_in(snap_black(Some(100_016), false, true), true, None),
            now + ms(32),
        );
        assert!(
            !m.pending_quit_out,
            "freeze write-back must not look like a quit-out"
        );
    }

    #[test]
    fn test_real_quit_out_still_detected_with_screen_signal_present() {
        // A regression never freezes (the freeze only fights forward
        // creep), so a genuine menu quit-out during a fade context still
        // arms the penalty even while the blackscreen flag reads true.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(
            tick_in(snap_black(Some(100_000), true, false), true, None),
            now,
        );
        let fx = m.tick(
            tick_in(snap_black(Some(97_000), false, true), true, None),
            now + ms(16),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));
        assert!(
            m.pending_quit_out,
            "regression through a fade is still a quit-out"
        );
    }

    #[test]
    fn test_freeze_baseline_resets_on_penalty() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx = quit_out_cycle(&mut m, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(
            m.freeze_last_igt, None,
            "penalty invalidates the frozen baseline"
        );

        // First fade frame after the penalty re-seeds from the penalized
        // IGT instead of freezing back to a pre-penalty value.
        let fx = m.tick(
            tick_in(snap_black(Some(10_516), true, true), true, None),
            now + ms(20),
        );
        assert!(!fx.iter().any(|e| matches!(e, Effect::FreezeIgt { .. })));
        assert_eq!(m.freeze_last_igt, Some(10_516));
        let fx = m.tick(
            tick_in(snap_black(Some(10_532), true, true), true, None),
            now + ms(40),
        );
        assert!(fx.contains(&Effect::FreezeIgt { ms: 10_516 }));
    }

    #[test]
    fn pending_flags_survive_ordinary_quit_out() {
        // Disconnected -> fog traversal parked as pending -> quit-out:
        // the small regression must NOT flush the pending buffer anymore.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);

        // Traversal while disconnected: flag captured then parked.
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(10_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(10_200), false), false, None), later);
        let mut input = tick_in(snap(Some(10_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(
            m.flag_buffer.has_pending(),
            "traversal parked while offline"
        );

        // Quit-out (2s regression) while still disconnected.
        m.tick(tick_in(snap(None, false), false, None), later);
        m.tick(tick_in(snap(Some(8_300), false), false, None), later);
        assert!(
            m.flag_buffer.has_pending(),
            "quit-out must not discard the parked traversal"
        );
        assert!(m.pending_quit_out, "still a quit-out (penalty armed)");
    }

    #[test]
    fn two_quit_out_cycles_pay_twice() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx1 = quit_out_cycle(&mut m, now);
        let fx2 = quit_out_cycle(&mut m, now + secs(10));
        assert_eq!(penalty_ms(&fx1), Some(2000));
        assert_eq!(penalty_ms(&fx2), Some(2000));
    }

    #[test]
    fn plain_reload_sends_untagged_query_and_no_penalty() {
        let now = Instant::now();
        let mut m = running_machine(now);
        // Death-style cycle: no bit, no title screen.
        m.tick(tick_in(snap(Some(1000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        let mut input = tick_in(snap(Some(1000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    #[test]
    fn replayed_zone_query_preserves_quit_out() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let fx = quit_out_cycle(&mut m, now);
        let message_id = fx
            .iter()
            .find_map(|e| match e {
                Effect::SendZoneQuery { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .unwrap();

        // Not ACKed: still in flight; a replay must keep the tag.
        let mut effects = Vec::new();
        m.replay_in_flight_zone_queries(&mut effects);
        assert!(effects.iter().any(|e| matches!(
            e,
            Effect::SendZoneQuery { message_id: id, quit_out: true, .. } if *id == message_id
        )));
    }

    // ------------------------------------------------------------------
    // Quit-out latch armed before race start
    // ------------------------------------------------------------------

    #[test]
    fn quit_out_armed_before_race_start_does_not_penalize_first_load() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        // Player quits out and reloads while waiting in setup for the race
        // to start: the regression arms the latch.
        m.tick(tick_in(snap(Some(50_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(48_500), false), true, None), now);
        assert!(m.pending_quit_out);

        m.handle_message(MachineMessage::RaceStart(3), now);
        assert!(!m.pending_quit_out, "race start clears the pre-race latch");

        // Load in once running, past the countdown: must NOT be treated as
        // a quit-out, since the armed latch predates the race.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(48_500), true), true, None),
            after_countdown,
        );
        m.tick(tick_in(snap(None, false), true, None), after_countdown);
        let mut input = tick_in(snap(Some(48_500), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    #[test]
    fn pre_start_igt_regression_does_not_penalize_first_load() {
        // Player loads their save during setup, quits to menu (probe misses
        // the title screen), waits for the start, then loads in after the
        // countdown: the reloaded save's IGT regresses vs the pre-start
        // observation but must not arm the latch.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);

        m.tick(tick_in(snap(Some(50_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);

        m.handle_message(MachineMessage::RaceStart(3), now);

        // Reload once running, past the countdown, with a regressed IGT.
        let after_countdown = now + secs(4);
        m.tick(
            tick_in(snap(Some(48_000), false), true, None),
            after_countdown,
        );
        assert!(!m.pending_quit_out, "pre-start regression must not arm");
        let mut input = tick_in(snap(Some(48_000), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, after_countdown);
        assert_eq!(penalty_ms(&fx), None);
        assert_eq!(sent_zone_query_quit_out(&fx), Some(false));
    }

    // ------------------------------------------------------------------
    // Transient zero IGT reads (menu/reload repopulation window)
    // ------------------------------------------------------------------

    #[test]
    fn transient_zero_igt_during_reload_is_ignored() {
        // Live log 2026-07-30: GameDataMan's play_time reads 0 transiently
        // while a menu reload repopulates it. Treated as a real observation
        // it misread an ordinary quit-out as a 67s rollback (no penalty),
        // poisoned last_good_igt to 0, and made the real post-reload value
        // look like an impossible forward jump (false wrong-save freeze).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(67_444), true), true, None), now);
        m.tick(tick_in(snap(Some(0), false), true, None), now);
        m.tick(tick_in(snap(Some(66_852), false), true, None), now);
        assert!(!m.wrong_save, "transient 0 must not poison the reference");
        assert!(
            m.pending_quit_out,
            "the real 592ms regression is a quit-out"
        );

        let mut input = tick_in(snap(Some(66_900), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now);
        assert_eq!(penalty_ms(&fx), Some(2000));
        assert_eq!(sent_zone_query_quit_out(&fx), Some(true));
    }

    #[test]
    fn transient_zero_igt_does_not_flush_buffers() {
        // Same transient while disconnected with a parked traversal: the 0
        // previously read as a 67s rollback and discarded the pending flag.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(67_000), true), false, None), now);
        let later = now + ms(150);
        m.tick(
            tick_in(snap(Some(67_100), true), false, Some(vec![(100, true)])),
            later,
        );
        m.tick(tick_in(snap(Some(67_200), false), false, None), later);
        let mut input = tick_in(snap(Some(67_300), true), false, None);
        input.flag_reads = Some(vec![]);
        m.tick(input, later);
        assert!(m.flag_buffer.has_pending());

        m.tick(tick_in(snap(Some(0), false), false, None), later);
        m.tick(tick_in(snap(Some(66_500), false), false, None), later);
        assert!(
            m.flag_buffer.has_pending(),
            "transient 0 must not flush the parked traversal"
        );
        assert!(m.pending_quit_out, "the real regression still arms");
    }

    #[test]
    fn frozen_machine_ignores_injected_flag_reads() {
        // The shell withholds flag reads while frozen (wants_flag_reads),
        // but the pure machine must also defend its own invariant: flag
        // reads injected during a freeze produce no game writes and no
        // sends.
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        let later = now + ms(150);
        let fx = m.tick(
            tick_in(snap(Some(7_200_100), true), true, Some(vec![(100, true)])),
            later,
        );
        assert!(
            fx.is_empty(),
            "frozen machine must ignore injected flag reads, got {fx:?}"
        );
        assert!(!m.flag_buffer.has_deferred());
    }

    #[test]
    fn transient_zero_igt_does_not_recover_a_freeze() {
        // With a small last_good the recovery window's low bound saturates
        // to 0: a transient 0 during a reload must not read as "race save
        // is back".
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);

        m.tick(tick_in(snap(Some(0), false), true, None), now);
        assert!(m.wrong_save, "transient 0 must not clear the freeze");
    }

    // ------------------------------------------------------------------
    // Deathless death banner
    // ------------------------------------------------------------------

    #[test]
    fn deathless_death_fires_banner_once() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        assert_eq!(m.get_status(now), None, "baseline tick must not banner");

        let t1 = now + secs(1);
        m.tick(tick_in(snap_deaths(Some(2000), 1), true, None), t1);
        assert_eq!(m.get_status(t1), Some("You died. Race over."));

        // Second death after the banner expired: latched, no new banner.
        let t2 = t1 + secs(10);
        m.tick(tick_in(snap_deaths(Some(3000), 2), true, None), t2);
        assert_eq!(m.get_status(t2), None);
    }

    #[test]
    fn deathless_banner_skipped_outside_conditions() {
        let now = Instant::now();

        // Not a deathless race.
        let mut m = running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);

        // Deathless but race still in setup.
        let mut m = deathless_machine("setup", now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);

        // Wrong-save guard active: frozen, no banner.
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.wrong_save = true;
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);
    }

    #[test]
    fn deathless_banner_skipped_when_already_finished() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running","deathless":true}"#)
                .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", "finished", 3)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), None);
    }

    #[test]
    fn deathless_first_observation_is_baseline_not_death() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        // Mid-race mod restart: counter already at 5. Must not banner.
        m.tick(tick_in(snap_deaths(Some(1000), 5), true, None), now);
        assert_eq!(m.get_status(now), None);
        // The NEXT increase is a real death.
        m.tick(
            tick_in(snap_deaths(Some(2000), 6), true, None),
            now + secs(1),
        );
        assert_eq!(m.get_status(now + secs(1)), Some("You died. Race over."));
    }

    #[test]
    fn race_start_resets_deathless_latch() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        m.tick(
            tick_in(snap_deaths(Some(2000), 1), true, None),
            now + secs(1),
        );
        assert!(m.deathless_banner_shown);
        m.handle_message(MachineMessage::RaceStart(0), now + secs(2));
        assert!(!m.deathless_banner_shown);
    }

    #[test]
    fn deathless_banner_gated_during_countdown() {
        let now = Instant::now();
        let mut m = deathless_running_machine(now);
        m.handle_message(MachineMessage::RaceStart(10), now);

        m.tick(tick_in(snap_deaths(Some(1000), 0), true, None), now);
        assert_eq!(m.get_status(now), None, "baseline tick must not banner");

        // Countdown death: still on the pre-race save, must not banner and
        // must not burn the one-shot latch.
        let t1 = now + secs(1);
        m.tick(tick_in(snap_deaths(Some(1000), 1), true, None), t1);
        assert_eq!(m.get_status(t1), None, "countdown death must not banner");
        assert!(
            !m.deathless_banner_shown,
            "countdown death must not consume the latch"
        );

        // Countdown over: the next death is a real in-race death.
        let t2 = now + secs(11);
        m.tick(tick_in(snap_deaths(Some(2000), 2), true, None), t2);
        assert_eq!(m.get_status(t2), Some("You died. Race over."));
    }

    // ------------------------------------------------------------------
    // Server conditions (coded errors) and the waiting line
    // ------------------------------------------------------------------

    fn coded_error(message: &str, kind: ConditionKind) -> MachineMessage {
        MachineMessage::Error {
            message: message.to_string(),
            code: Some(kind),
        }
    }

    #[test]
    fn blocking_condition_displays_then_expires() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Wrong save loaded", ConditionKind::WrongSave),
            now,
        );

        assert_eq!(
            m.get_blocking_condition(now).map(|c| c.message.as_str()),
            Some("Wrong save loaded")
        );
        // Not a transient status: the coded path bypasses set_status.
        assert_eq!(m.get_status(now), None);
        assert_eq!(
            m.get_waiting_line(now),
            None,
            "a blocking condition must not double-render as the waiting line"
        );
        // Fresh again after a re-send, gone 3s after the last one.
        m.handle_message(
            coded_error("Wrong save loaded", ConditionKind::WrongSave),
            now + secs(2),
        );
        assert!(m.get_blocking_condition(now + secs(4)).is_some());
        assert!(m.get_blocking_condition(now + secs(6)).is_none());
    }

    #[test]
    fn waiting_condition_is_not_blocking() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Race not running", ConditionKind::RaceNotRunning),
            now,
        );
        assert!(m.get_blocking_condition(now).is_none());
        assert_eq!(m.get_waiting_line(now), Some("Race not running"));
        assert_eq!(m.get_waiting_line(now + secs(4)), None);
    }

    #[test]
    fn unknown_code_falls_back_to_transient_status() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.handle_message(
            coded_error("Some future thing", ConditionKind::Unknown),
            now,
        );
        assert!(m.get_blocking_condition(now).is_none());
        assert_eq!(m.get_status(now), Some("Some future thing"));
    }

    #[test]
    fn waiting_line_derived_from_setup_even_offline() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        // In world, no server condition, disconnected: local derivation.
        m.tick(tick_in(snap(Some(1_000), true), false, None), now);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
        m.handle_message(MachineMessage::RaceStart(0), now);
        assert_eq!(m.get_waiting_line(now + secs(1)), None);
    }

    #[test]
    fn waiting_line_hidden_outside_the_world() {
        // Regression (live 2026-07-31): the derived setup line rendered at
        // the title screen, before any save was loaded. It must only show
        // while the player is actually in the world.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        assert_eq!(m.get_waiting_line(now), None, "title screen: no line");
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
        // Back out of the world (quit to menu): the line hides again.
        m.tick(tick_in(snap(None, false), true, None), now);
        assert_eq!(m.get_waiting_line(now), None, "menu: no line");
    }

    #[test]
    fn countdown_code_suppressed_while_local_countdown_active() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        m.handle_message(MachineMessage::RaceStart(10), now);
        assert!(m.is_countdown_active(now + secs(1)));
        m.handle_message(
            coded_error("Race countdown in progress", ConditionKind::Countdown),
            now + secs(1),
        );
        assert_eq!(m.get_waiting_line(now + secs(1)), None);
        // After the countdown, a fresh countdown condition would display
        // (desync case), pinned via a re-send past the countdown end.
        m.handle_message(
            coded_error("Race countdown in progress", ConditionKind::Countdown),
            now + secs(11),
        );
        assert_eq!(
            m.get_waiting_line(now + secs(11)),
            Some("Race countdown in progress")
        );
    }

    #[test]
    fn auth_error_flash_suppressed_when_permanent_error_shown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(
            MachineMessage::PermanentError("Invalid mod token or race".to_string()),
            now,
        );
        m.handle_message(MachineMessage::StatusChanged(ConnectionStatus::Error), now);
        assert_eq!(
            m.get_status(now),
            None,
            "no gold flash under the red banner"
        );
    }

    #[test]
    fn setup_save_load_no_longer_flashes_transient_status() {
        // The old 3s "Race hasn't started yet" flash is replaced by the
        // persistent derived waiting line.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100], Some(900)), now);
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        m.tick(tick_in(snap(Some(1_000), true), true, None), now);
        assert_eq!(m.get_status(now), None);
        assert_eq!(m.get_waiting_line(now), Some("Race has not started yet"));
    }

    // ------------------------------------------------------------------
    // Cheat detection (game debug flags)
    // ------------------------------------------------------------------

    fn debug_bit(name: &str) -> u32 {
        1 << crate::core::debug_flags::DEBUG_FLAGS
            .iter()
            .position(|f| f.name == name)
            .unwrap()
    }

    /// In-world snapshot carrying a debug-flag read.
    fn snap_flags(igt: u32, mask: u32) -> FrameSnapshot {
        FrameSnapshot {
            debug_flags: Some(mask),
            ..snap(Some(igt), true)
        }
    }

    #[test]
    fn debug_flags_read_requested_at_10hz_while_racing() {
        let now = Instant::now();
        let mut m = running_machine(now);
        assert!(
            !m.pre_tick(now, true, true).debug_flags,
            "100 ms not elapsed yet"
        );
        let t1 = now + ms(100);
        assert!(m.pre_tick(t1, true, true).debug_flags);
        m.tick(tick_in(snap_flags(1000, 0), true, None), t1);
        assert!(!m.pre_tick(t1 + ms(50), true, true).debug_flags);
        assert!(m.pre_tick(t1 + ms(100), true, true).debug_flags);
    }

    #[test]
    fn debug_flags_not_read_in_normal_training() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), true, now);
        m.handle_message(auth_ok("running", &[100, 200, 900], Some(900)), now);
        assert!(!m.pre_tick(now + secs(1), true, true).debug_flags);
    }

    #[test]
    fn debug_flags_read_in_ranked_training() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), true, now);
        let mut race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running","ranked":true}"#)
                .unwrap();
        race.reparse_dates();
        m.handle_message(
            MachineMessage::AuthOk {
                participant_id: "p1".to_string(),
                race,
                seed: test_seed(&[100, 200, 900], Some(900), "{}"),
                participants: vec![test_participant("p1", "playing", 1)],
                phantom_skin: None,
                latest_mod_version: None,
                held_item: None,
                relay: None,
            },
            now,
        );
        assert!(m.pre_tick(now + secs(1), true, true).debug_flags);
    }

    #[test]
    fn debug_flags_not_read_before_start_or_during_countdown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);
        assert!(!m.pre_tick(now + secs(1), true, true).debug_flags, "setup");

        m.handle_message(MachineMessage::RaceStart(10), now + secs(1));
        assert!(
            !m.pre_tick(now + secs(5), true, true).debug_flags,
            "countdown"
        );
        assert!(m.pre_tick(now + secs(12), true, true).debug_flags, "racing");
    }

    #[test]
    fn debug_flags_accumulate_and_banner_follows_latest_read() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        assert!(m.cheat_warning_active(t1));

        let t2 = t1 + ms(100);
        m.tick(tick_in(snap_flags(1100, 0), true, None), t2);
        assert!(
            !m.cheat_warning_active(t2),
            "the banner follows the latest read"
        );
        assert_eq!(
            m.debug_flags_seen,
            debug_bit("one_shot"),
            "the report keeps it"
        );

        let t3 = t2 + ms(100);
        m.tick(
            tick_in(snap_flags(1200, debug_bit("infinite_stamina")), true, None),
            t3,
        );
        assert_eq!(
            m.debug_flags_seen,
            debug_bit("one_shot") | debug_bit("infinite_stamina")
        );
    }

    #[test]
    fn banner_drops_when_the_runner_finishes_with_a_flag_still_on() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        assert!(m.cheat_warning_active(t1));

        m.race_state.participants[0].status = ParticipantStatus::Finished;
        let t2 = t1 + ms(100);
        assert!(
            !m.pre_tick(t2, true, true).debug_flags,
            "no read after the finish"
        );
        m.tick(tick_in(snap(Some(2000), true), true, None), t2);
        assert!(!m.cheat_warning_active(t2), "no stale banner");
    }

    #[test]
    fn debug_flags_reset_on_race_start() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        // A reset race starts again: the earlier attempt's flags are not this run's.
        m.handle_message(MachineMessage::RaceStart(0), t1 + secs(1));
        assert_eq!(m.debug_flags_seen, 0);
        assert!(!m.cheat_warning_active(t1 + secs(1)));
    }

    #[test]
    fn cheat_banner_yields_to_other_red_banners() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        m.permanent_error = Some("Race deleted".to_string());
        assert!(!m.cheat_warning_active(t1));
    }

    #[test]
    fn status_update_carries_flags_seen_since_start() {
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        // Off again before the next status update: still reported.
        let t2 = now + secs(1);
        let effects = m.tick(tick_in(snap_flags(1900, 0), true, None), t2);
        let sent = effects.iter().find_map(|e| match e {
            Effect::SendStatusUpdate { debug_flags, .. } => Some(*debug_flags),
            _ => None,
        });
        assert_eq!(sent, Some(debug_bit("one_shot")));
    }

    #[test]
    fn no_banner_or_report_after_the_runner_abandons() {
        // The server ignores an abandoned runner's updates: a banner saying
        // "reported" would be false (e.g. exploring with a tool after a
        // deathless death).
        let now = Instant::now();
        let mut m = running_machine(now);
        m.race_state.participants[0].status = ParticipantStatus::Abandoned;
        let t1 = now + ms(100);
        assert!(
            !m.pre_tick(t1, true, true).debug_flags,
            "no read once abandoned"
        );
        m.tick(
            tick_in(snap_flags(1000, debug_bit("one_shot")), true, None),
            t1,
        );
        assert!(!m.cheat_warning_active(t1));
        assert_eq!(m.debug_flags_seen, 0);
    }

    #[test]
    fn flags_seen_on_a_save_the_server_rejects_are_not_reported() {
        // Async race: the runner practises with a tool on an old save, the
        // server refuses it (fresh save required), the runner starts a clean
        // New Game with the tool off. Nothing from the old save is reported.
        let now = Instant::now();
        let mut m = running_machine(now);
        let t1 = now + ms(100);
        m.tick(
            tick_in(snap_flags(500_000, debug_bit("one_shot")), true, None),
            t1,
        );
        let t2 = t1 + ms(900);
        m.handle_message(
            coded_error("Please start a New Game", ConditionKind::FreshSaveRequired),
            t2,
        );
        let t3 = t2 + ms(100);
        assert!(
            !m.pre_tick(t3, true, true).debug_flags,
            "no read while the server blocks"
        );
        m.tick(
            tick_in(snap_flags(500_100, debug_bit("one_shot")), true, None),
            t3,
        );
        assert_eq!(
            m.debug_flags_seen, 0,
            "the rejected save's flags are dropped"
        );

        // New Game, tool off: once the condition lapses, reads resume, clean.
        let t4 = t2 + secs(4);
        assert!(m.pre_tick(t4, true, true).debug_flags);
        m.tick(tick_in(snap_flags(1000, 0), true, None), t4);
        assert_eq!(m.debug_flags_seen, 0);
    }

    #[test]
    fn disqualified_runner_is_out_like_an_abandon() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.race_state.participants[0].status = ParticipantStatus::Disqualified;
        assert!(m.am_i_disqualified());
        assert!(
            m.am_i_abandoned(),
            "out of the race: same gates as an abandon"
        );
        assert!(!m.pre_tick(now + ms(100), true, true).debug_flags);
    }

    // ------------------------------------------------------------------
    // LiveSplit run view
    // ------------------------------------------------------------------

    /// auth_ok from a protocol 1.10 server: flags 100 and 200 lead to layers
    /// 1 and 2 (of 3), 900 is the finish; `arrivals` is the local runner's
    /// `layer_entry_igts`.
    fn ls_auth_ok(status: &str, my_status: &str, arrivals: &[(i32, i32)]) -> MachineMessage {
        let mut seed = test_seed(&[100, 200, 900], Some(900), "{}");
        seed.flag_layers = HashMap::from([(100, 1), (200, 2)]);
        seed.seed_number = Some("s1".to_string());
        let mut me = test_participant("p1", my_status, 0);
        me.layer_entry_igts = Some(arrivals.iter().copied().collect());
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed,
            participants: vec![me],
            phantom_skin: None,
            latest_mod_version: None,
            held_item: None,
            relay: None,
        }
    }

    /// Machine authed with `ls_auth_ok`, and the effects of that auth_ok.
    fn ls_machine(
        status: &str,
        my_status: &str,
        arrivals: &[(i32, i32)],
        training: bool,
        now: Instant,
    ) -> (RaceMachine, Vec<Effect>) {
        let mut m = RaceMachine::new(1, String::new(), training, now);
        let fx = m.handle_message(ls_auth_ok(status, my_status, arrivals), now);
        (m, fx)
    }

    fn run_views(effects: &[Effect]) -> Vec<&RunView> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::LiveSplitRun(view) => Some(view.as_ref()),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn fog_capture_records_its_depth_at_the_capture_igt() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("running", "playing", &[], false, now);
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, Some(vec![(100, true)])),
            now + ms(150),
        );
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].arrivals, vec![None, Some(60_000), None, None]);
        assert!(views[0].live);
        assert!(!views[0].fresh);
    }

    #[test]
    fn back_out_to_a_reached_depth_records_nothing() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("running", "playing", &[], false, now);
        let t1 = now + ms(150);
        m.tick(
            tick_in(snap(Some(60_000), true), true, Some(vec![(100, true)])),
            t1,
        );
        // Loading screen, then the exit scan catches the next fog's flag.
        m.tick(tick_in(snap(Some(60_100), false), true, None), t1 + ms(50));
        let fx = m.tick(
            tick_in(snap(Some(60_200), true), true, Some(vec![(200, true)])),
            t1 + ms(80),
        );
        assert_eq!(
            run_views(&fx)[0].arrivals,
            vec![None, Some(60_000), Some(60_200), None]
        );

        // Back out through the first fog: layer 1 again.
        let fx = m.tick(
            tick_in(snap(Some(90_000), true), true, Some(vec![(100, true)])),
            t1 + ms(300),
        );
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: 100,
            value: false
        }));
        assert!(run_views(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn finish_records_the_last_depth() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("running", "playing", &[(1, 5_000), (2, 9_000)], false, now);
        let fx = m.tick(
            tick_in(snap(Some(1_800_000), true), true, Some(vec![(900, true)])),
            now + ms(150),
        );
        assert_eq!(
            run_views(&fx)[0].arrivals,
            vec![None, Some(5_000), Some(9_000), Some(1_800_000)]
        );
    }

    #[test]
    fn auth_ok_fills_arrivals_from_the_server() {
        let (_, fx) = ls_machine(
            "running",
            "playing",
            &[(0, 0), (1, 5_000)],
            false,
            Instant::now(),
        );
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].arrivals, vec![None, Some(5_000), None, None]);
        assert!(!views[0].fresh);
        assert_eq!(views[0].seed_number.as_deref(), Some("s1"));
    }

    #[test]
    fn race_start_without_progress_bumps_the_attempt() {
        let now = Instant::now();
        let (mut m, fx) = ls_machine("setup", "ready", &[], false, now);
        let before = run_views(&fx)[0].attempt;

        let fx = m.handle_message(MachineMessage::RaceStart(3), now);
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].attempt, before.wrapping_add(1));
        assert!(views[0].fresh);
        assert!(!views[0].live, "still in the countdown");

        // The countdown ends: the same attempt goes live.
        let fx = m.tick(tick_in(snap(Some(1_000), true), true, None), now + secs(4));
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert!(views[0].live);
        assert_eq!(views[0].attempt, before.wrapping_add(1));
    }

    #[test]
    fn a_race_reset_restarts_the_attempt_without_the_voided_depths() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("setup", "ready", &[], false, now);
        m.handle_message(MachineMessage::RaceStart(0), now);
        let fx = m.tick(
            tick_in(snap(Some(30_000), true), true, Some(vec![(100, true)])),
            now + ms(150),
        );
        let voided = run_views(&fx)[0].clone();
        assert_eq!(voided.arrivals[1], Some(30_000));

        // The organizer resets the race: the server closes the connection,
        // the mod reconnects into setup, then the re-run starts.
        let t = now + secs(60);
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            t,
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t,
        );
        m.handle_message(ls_auth_ok("setup", "ready", &[]), t);
        let fx = m.handle_message(MachineMessage::RaceStart(3), t);
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].attempt, voided.attempt.wrapping_add(1));
        assert!(views[0].fresh);
        assert_eq!(views[0].arrivals, vec![None; 4]);

        // The re-run's first fog counts again.
        let fx = m.tick(
            tick_in(snap(Some(40_000), true), true, Some(vec![(100, true)])),
            t + secs(4),
        );
        assert_eq!(run_views(&fx)[0].arrivals[1], Some(40_000));
    }

    #[test]
    fn a_solo_race_start_keeps_the_attempt() {
        // A solo session's auth_ok already says running, and its server
        // sends race_start after every auth_ok, reconnects included: no
        // start, so no new attempt that would restart LiveSplit mid-run.
        let now = Instant::now();
        let (mut m, fx) = ls_machine("running", "playing", &[], true, now);
        let first = run_views(&fx)[0].clone();
        assert!(first.live && first.fresh);
        let fx = m.handle_message(MachineMessage::RaceStart(0), now);
        assert!(run_views(&fx).is_empty(), "{fx:?}");

        // A reconnect before the first fog.
        m.tick(
            tick_in(snap(Some(180_000), true), true, None),
            now + secs(180),
        );
        let t = now + secs(181);
        let mut fx = m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            t,
        );
        fx.extend(m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t,
        ));
        fx.extend(m.handle_message(ls_auth_ok("running", "playing", &[]), t));
        fx.extend(m.handle_message(MachineMessage::RaceStart(0), t));
        fx.extend(m.tick(tick_in(snap(Some(181_000), true), true, None), t));
        assert!(
            run_views(&fx).iter().all(|v| v.attempt == first.attempt),
            "{fx:?}"
        );
    }

    #[test]
    fn fresh_character_after_a_save_reload_starts_a_new_attempt() {
        let now = Instant::now();
        let (mut m, fx) = ls_machine("running", "playing", &[], false, now);
        let before = run_views(&fx)[0].attempt;
        m.tick(
            tick_in(snap(Some(600_000), true), true, Some(vec![(100, true)])),
            now + ms(150),
        );

        // A backup restore is the same run: nothing changes.
        m.tick(tick_in(snap(None, false), true, None), now + secs(5));
        let fx = m.tick(
            tick_in(snap(Some(500_000), false), true, None),
            now + secs(20),
        );
        assert!(run_views(&fx).is_empty(), "{fx:?}");

        // Back to the title, then a New Game.
        m.tick(tick_in(snap(None, false), true, None), now + secs(25));
        let fx = m.tick(
            tick_in(snap(Some(20_000), false), true, None),
            now + secs(40),
        );
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].attempt, before.wrapping_add(1));
        assert!(views[0].fresh);
        assert_eq!(views[0].arrivals, vec![None; 4]);
    }

    #[test]
    fn wrong_save_turns_the_view_not_live_and_back() {
        let now = Instant::now();
        let (mut m, fx) = ls_machine("running", "playing", &[], false, now);
        let attempt = run_views(&fx)[0].attempt;
        m.tick(tick_in(snap(Some(10_000), true), true, None), now);
        m.tick(tick_in(snap(None, false), true, None), now);
        let fx = m.tick(tick_in(snap(Some(7_200_000), false), true, None), now);
        assert!(m.wrong_save);
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert!(!views[0].live);
        assert_eq!(views[0].attempt, attempt);

        // The race save comes back.
        m.tick(tick_in(snap(None, false), true, None), now + secs(90));
        let fx = m.tick(
            tick_in(snap(Some(9_000), false), true, None),
            now + secs(90),
        );
        assert!(!m.wrong_save);
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert!(views[0].live);
        assert_eq!(views[0].attempt, attempt);
    }

    #[test]
    fn no_view_without_flag_layers() {
        // An old server's auth_ok has no flag layers: LiveSplit is left alone.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        let mut fx = m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);
        fx.extend(m.handle_message(MachineMessage::RaceStart(0), now));
        fx.extend(m.tick(
            tick_in(snap(Some(60_000), true), true, Some(vec![(100, true)])),
            now + ms(150),
        ));
        fx.extend(m.tick(
            tick_in(snap(Some(90_000), true), true, Some(vec![(900, true)])),
            now + ms(300),
        ));
        assert!(run_views(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn steady_frames_emit_no_view() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("running", "playing", &[(1, 5_000)], false, now);
        for i in 1..=10 {
            let fx = m.tick(
                tick_in(
                    snap(Some(60_000), true),
                    true,
                    Some(vec![(100, false), (200, false), (900, false)]),
                ),
                now + ms(150 * i),
            );
            assert!(run_views(&fx).is_empty(), "tick {i}: {fx:?}");
        }
    }

    #[test]
    fn an_abandoned_runner_captures_no_depth() {
        let now = Instant::now();
        let (mut m, _) = ls_machine("running", "playing", &[], false, now);
        let mut me = m.race_state.participants[0].clone();
        me.status = ParticipantStatus::Abandoned;
        let fx = m.handle_message(MachineMessage::PlayerUpdate(me), now);
        assert!(!run_views(&fx)[0].live);

        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, Some(vec![(100, true)])),
            now + ms(150),
        );
        assert!(run_views(&fx).is_empty(), "{fx:?}");
    }

    // ------------------------------------------------------------------
    // Unacknowledged flags across game restarts
    // ------------------------------------------------------------------

    fn unacked(participant: &str, flags: &[(u32, u32, Option<u64>)]) -> UnackedFlags {
        UnackedFlags {
            participant_id: participant.to_string(),
            attempt_id: None,
            flags: flags
                .iter()
                .map(|&(flag_id, igt_ms, message_id)| UnackedFlag {
                    flag_id,
                    igt_ms,
                    message_id,
                })
                .collect(),
        }
    }

    fn persisted(effects: &[Effect]) -> Vec<&UnackedFlags> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::PersistUnackedFlags(flags) => Some(flags),
                _ => None,
            })
            .collect()
    }

    /// `(flag_id, igt_ms, message_id)` of every event_flag sent.
    fn sent_flag_details(effects: &[Effect]) -> Vec<(u32, u32, u64)> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendEventFlag {
                    flag_id,
                    igt_ms,
                    message_id,
                } => Some((*flag_id, *igt_ms, *message_id)),
                _ => None,
            })
            .collect()
    }

    /// A new game process holding what the previous one saved, authed into
    /// the running race of `running_machine` (as participant p1) and
    /// connected while still on the title screen.
    fn relaunched(saved: UnackedFlags, race_status: &str, now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(saved);
        m.handle_message(auth_ok(race_status, &[100, 200, 900], Some(900)), now);
        // Title screen: no IGT yet, `ready` goes out.
        m.tick(tick_in(snap(None, false), true, None), now + ms(10));
        m
    }

    #[test]
    fn unacked_flag_is_saved_until_the_server_acknowledges_it() {
        let now = Instant::now();
        let mut m = running_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Fog crossed: captured during the fade, not sent yet.
        let fx = m.tick(
            tick_in(
                snap(Some(1000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        assert_eq!(persisted(&fx), vec![&unacked("p1", &[(100, 1000, None)])]);

        // Nothing changed: nothing to write.
        let fx = m.tick(tick_in(snap(Some(1100), false), true, None), now + ms(200));
        assert!(persisted(&fx).is_empty());

        // Loading exit: sent, saved again with its message id for a replay.
        let fx = m.tick(
            tick_in(snap(Some(1300), true), true, Some(vec![])),
            now + ms(300),
        );
        let id = sent_message_ids(&fx)[0];
        assert_eq!(
            persisted(&fx),
            vec![&unacked("p1", &[(100, 1000, Some(id))])]
        );

        let fx = m.handle_message(
            MachineMessage::EventFlagAck { message_id: id },
            now + ms(400),
        );
        assert_eq!(persisted(&fx), vec![&unacked("p1", &[])]);
    }

    #[test]
    fn flag_lost_with_a_closed_game_is_sent_with_its_capture_igt() {
        // Daily 2026-10-12: fog crossed offline at ~15:42 IGT, game closed,
        // relaunched; the mod connects on the title screen, then the save
        // loads at 16:49.
        let now = Instant::now();
        let mut m = relaunched(unacked("p1", &[(100, 942_000, None)]), "running", now);

        let fx = m.tick(
            tick_in(snap(Some(1_009_414), false), true, None),
            now + secs(10),
        );
        let sent = sent_flag_details(&fx);
        assert_eq!(sent.len(), 1, "sent without waiting for a reconnection");
        assert_eq!((sent[0].0, sent[0].1), (100, 942_000));
    }

    #[test]
    fn restored_in_flight_flag_is_replayed_with_its_message_id() {
        let now = Instant::now();
        let mut m = relaunched(unacked("p1", &[(100, 5_000, Some(42))]), "running", now);

        let fx = m.tick(
            tick_in(snap(Some(10_000), false), true, None),
            now + secs(10),
        );
        assert_eq!(sent_flag_details(&fx), vec![(100, 5_000, 42)]);
    }

    #[test]
    fn restored_flags_ahead_of_a_restored_save_are_dropped() {
        // The save loads 70 s before the first flag (a backup restore): that
        // traversal is not in it. The second one, 30 s before, is.
        let now = Instant::now();
        let saved = unacked("p1", &[(100, 220_000, None), (200, 120_000, None)]);
        let mut m = relaunched(saved, "running", now);

        let fx = m.tick(
            tick_in(snap(Some(150_000), false), true, None),
            now + secs(10),
        );
        let sent: Vec<_> = sent_flag_details(&fx)
            .iter()
            .map(|&(flag, igt, _)| (flag, igt))
            .collect();
        assert_eq!(sent, vec![(200, 120_000)]);
    }

    #[test]
    fn restored_flags_are_judged_against_the_save_loaded_at_launch() {
        // Launched offline: the save loads 70 s before the flag, the runner
        // plays on, and only then the mod connects. The later IGT must not
        // make the stale flag look like part of this save.
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p1", &[(100, 1_080_000, None)]));
        m.tick(
            tick_in(snap(Some(1_010_000), false), false, None),
            now + secs(1),
        );
        m.tick(
            tick_in(snap(Some(1_150_000), true), false, None),
            now + secs(150),
        );

        m.handle_message(
            auth_ok("running", &[100, 200, 900], Some(900)),
            now + secs(151),
        );
        let fx = m.tick(
            tick_in(snap(Some(1_151_000), true), true, None),
            now + secs(152),
        );
        assert!(sent_flags(&fx).is_empty());
    }

    #[test]
    fn restored_flags_of_another_participant_are_dropped() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p2", &[(100, 942_000, None)]));

        let fx = m.handle_message(auth_ok("running", &[100, 200, 900], Some(900)), now);
        assert_eq!(persisted(&fx), vec![&unacked("p1", &[])]);
        m.tick(tick_in(snap(None, false), true, None), now + ms(10));
        let fx = m.tick(
            tick_in(snap(Some(1_009_414), false), true, None),
            now + secs(10),
        );
        assert!(sent_flags(&fx).is_empty());
    }

    /// `auth_ok` of `running_machine`'s race whose attempt is `attempt`.
    fn auth_ok_attempt(attempt: &str) -> MachineMessage {
        let mut msg = auth_ok("running", &[100, 200, 900], Some(900));
        if let MachineMessage::AuthOk { ref mut race, .. } = msg {
            race.attempt_id = Some(attempt.to_string());
        }
        msg
    }

    /// Flags saved in attempt `saved_in`, restored by a launch whose auth_ok
    /// names attempt `current`; the New Game loads at 5 s of IGT. Returns the
    /// event flags sent and the last save.
    fn restore_across_attempts(saved_in: &str, current: &str) -> (Vec<u32>, UnackedFlags) {
        let now = Instant::now();
        let mut saved = unacked("p1", &[(100, 30_000, None)]);
        saved.attempt_id = Some(saved_in.to_string());
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(saved);
        let mut fx = m.handle_message(auth_ok_attempt(current), now);
        fx.extend(m.tick(tick_in(snap(None, false), true, None), now + ms(10)));
        fx.extend(m.tick(
            tick_in(snap(Some(5_000), false), true, None),
            now + secs(10),
        ));
        let last_save = persisted(&fx).last().map(|&saved| saved.clone());
        (sent_flags(&fx), last_save.expect("a save"))
    }

    #[test]
    fn restored_flags_of_a_reset_attempt_are_dropped() {
        // Set Seed reset (or race reset and rerun) with the game closed: the
        // flag from the first minute of the old attempt is within 60 s of the
        // New Game's IGT, yet it belongs to the old attempt.
        let (sent, last_save) = restore_across_attempts("0", "1");
        assert!(sent.is_empty(), "{sent:?}");
        assert!(last_save.flags.is_empty());
        assert_eq!(last_save.attempt_id.as_deref(), Some("1"));
    }

    #[test]
    fn restored_flags_of_the_same_attempt_are_sent() {
        let (sent, _) = restore_across_attempts("1", "1");
        assert_eq!(sent, vec![100]);
    }

    #[test]
    fn a_race_joined_in_setup_saves_its_flags_under_the_started_attempt() {
        // The usual organized race: auth and ready in setup, the race starts
        // with the mod connected, then the connection drops and a fog is
        // crossed before the game closes. The start's race_info_update names
        // the attempt; without it the flags were saved under none and the
        // relaunch dropped them.
        let now = Instant::now();
        let attempt = "2026-11-11T20:00:00+00:00";
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.handle_message(auth_ok("setup", &[100, 200, 900], Some(900)), now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        m.handle_message(MachineMessage::RaceStart(0), now + ms(20));
        let mut race = test_race("running");
        race.attempt_id = Some(attempt.to_string());
        m.handle_message(MachineMessage::RaceInfoUpdate(race), now + ms(30));

        let fx = m.tick(
            tick_in(
                snap(Some(30_000), true),
                false,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + secs(30),
        );
        let saved = persisted(&fx).last().map(|&saved| saved.clone());
        let saved = saved.expect("the capture is saved");
        assert_eq!(saved.attempt_id.as_deref(), Some(attempt));

        let mut relaunch = RaceMachine::new(2_000_000, String::new(), false, now);
        relaunch.restore_unacked(saved);
        relaunch.handle_message(auth_ok_attempt(attempt), now + secs(60));
        relaunch.tick(tick_in(snap(None, false), true, None), now + secs(61));
        let fx = relaunch.tick(
            tick_in(snap(Some(29_000), false), true, None),
            now + secs(70),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
    }

    #[test]
    fn a_restored_fog_records_its_depth() {
        // Crossed offline, game closed: the relaunch must not leave a
        // skipped split for that depth.
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p1", &[(100, 50_000, None)]));
        m.handle_message(ls_auth_ok("running", "playing", &[]), now);
        m.tick(tick_in(snap(None, false), true, None), now + ms(10));
        let fx = m.tick(
            tick_in(snap(Some(55_000), false), true, None),
            now + secs(10),
        );
        let views = run_views(&fx);
        assert_eq!(views.len(), 1, "{fx:?}");
        assert_eq!(views[0].arrivals, vec![None, Some(50_000), None, None]);
    }

    #[test]
    fn restored_flags_are_dropped_once_the_race_is_over() {
        let now = Instant::now();
        let mut m = relaunched(unacked("p1", &[(100, 942_000, None)]), "finished", now);

        let fx = m.tick(
            tick_in(snap(Some(1_009_414), false), true, None),
            now + secs(10),
        );
        assert!(sent_flags(&fx).is_empty());
        assert_eq!(persisted(&fx), vec![&unacked("p1", &[])]);
    }

    #[test]
    fn restored_finish_is_not_sent_again_by_the_loading_exit_scan() {
        // The finish flag stays set in the save: the scan at the loading exit
        // sees it too, and must not report it a second time at the later IGT.
        let now = Instant::now();
        let mut m = relaunched(unacked("p1", &[(900, 500_000, None)]), "running", now);

        let fx = m.tick(
            tick_in(snap(Some(520_000), false), true, None),
            now + secs(10),
        );
        let fx2 = m.tick(
            tick_in(
                snap(Some(520_100), true),
                true,
                Some(vec![(100, false), (200, false), (900, true)]),
            ),
            now + secs(11),
        );
        let sent: Vec<_> = sent_flag_details(&fx)
            .into_iter()
            .chain(sent_flag_details(&fx2))
            .map(|(flag, igt, _)| (flag, igt))
            .collect();
        assert_eq!(sent, vec![(900, 500_000)]);
    }

    #[test]
    fn restored_flags_still_held_follow_a_backup_loaded_later() {
        // Launched offline: the race save loads 10 s after the flag, then
        // the runner loads a backup 5 minutes older before the mod connects.
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p1", &[(100, 1_090_000, None)]));
        m.tick(
            tick_in(snap(Some(1_100_000), false), false, None),
            now + secs(1),
        );
        m.tick(
            tick_in(snap(Some(1_100_500), true), false, None),
            now + secs(2),
        );
        m.tick(tick_in(snap(None, false), false, None), now + secs(5));
        m.tick(
            tick_in(snap(Some(800_000), false), false, None),
            now + secs(8),
        );
        m.tick(
            tick_in(snap(Some(800_100), true), false, None),
            now + secs(9),
        );

        m.handle_message(
            auth_ok("running", &[100, 200, 900], Some(900)),
            now + secs(10),
        );
        let fx = m.tick(
            tick_in(snap(Some(801_000), true), true, None),
            now + secs(11),
        );
        assert!(sent_flags(&fx).is_empty());
    }

    #[test]
    fn restored_flags_go_out_before_the_first_zone_query() {
        // The save's first IGT and the loading exit on the same frame: the
        // zone query must not reach the server before the older traversal.
        let now = Instant::now();
        let mut m = relaunched(unacked("p1", &[(100, 942_000, None)]), "running", now);

        let mut input = tick_in(snap(Some(1_009_414), true), true, None);
        input.position = Some(PlayerPosition {
            map_id: 0x10000000,
            map_id_str: "m16_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let fx = m.tick(input, now + secs(10));
        let flag_at = fx
            .iter()
            .position(|e| matches!(e, Effect::SendEventFlag { flag_id: 100, .. }));
        let query_at = fx
            .iter()
            .position(|e| matches!(e, Effect::SendZoneQuery { .. }));
        assert!(
            query_at.is_some(),
            "the loading exit still queries the zone"
        );
        assert!(
            flag_at < query_at,
            "flag at {flag_at:?}, query at {query_at:?}"
        );
    }

    #[test]
    fn flag_restored_before_the_connection_is_sent_once() {
        // Launched offline: the save loads before auth_ok, so the flags are
        // restored before `ready` and go out with the reconnection's sends.
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p1", &[(100, 942_000, None)]));
        m.tick(
            tick_in(snap(Some(1_009_414), true), false, None),
            now + secs(1),
        );
        m.handle_message(
            auth_ok("running", &[100, 200, 900], Some(900)),
            now + secs(2),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(2),
        );

        let fx1 = m.tick(
            tick_in(snap(Some(1_010_000), true), true, None),
            now + secs(3),
        );
        let fx2 = m.tick(
            tick_in(snap(Some(1_011_000), true), true, None),
            now + secs(4),
        );
        let sent: Vec<_> = sent_flag_details(&fx1)
            .into_iter()
            .chain(sent_flag_details(&fx2))
            .map(|(flag, igt, _)| (flag, igt))
            .collect();
        assert_eq!(sent, vec![(100, 942_000)]);
    }

    #[test]
    fn new_flags_never_reuse_a_restored_message_id() {
        // The PC clock went back between launches: this launch's ids start
        // at the id a restored flag already carries.
        let now = Instant::now();
        let mut m = relaunched(
            unacked("p1", &[(100, 5_000, Some(1_000_000))]),
            "running",
            now,
        );
        m.tick(
            tick_in(snap(Some(10_000), true), true, None),
            now + secs(10),
        );

        // A new fog crossed, then its loading exit.
        m.tick(
            tick_in(
                snap(Some(11_000), true),
                true,
                Some(vec![(100, false), (200, true), (900, false)]),
            ),
            now + secs(11),
        );
        m.tick(
            tick_in(snap(Some(11_500), false), true, None),
            now + secs(12),
        );
        let fx = m.tick(
            tick_in(snap(Some(12_000), true), true, Some(vec![])),
            now + secs(13),
        );
        let ids = sent_message_ids(&fx);
        assert_eq!(ids.len(), 1);
        assert_ne!(ids[0], 1_000_000);
    }

    // ------------------------------------------------------------------
    // Boss defeat flags
    // ------------------------------------------------------------------

    /// auth_ok of `auth_ok` (flags [100, 200, 900], finish 900) whose seed
    /// also names `boss_flags`.
    fn auth_ok_with_bosses(status: &str, boss_flags: &[u32]) -> MachineMessage {
        let seed: SeedInfo = serde_json::from_str(&format!(
            r#"{{"total_layers": 3, "event_ids": [100, 200, 900], "finish_event": 900,
                 "death_flags": {{}}, "boss_flags": {:?}}}"#,
            boss_flags
        ))
        .unwrap();
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed,
            participants: vec![test_participant("p1", "playing", 1)],
            phantom_skin: None,
            latest_mod_version: None,
            held_item: None,
            relay: None,
        }
    }

    /// `running_machine` with the boss defeat flag 5_000_800.
    fn running_boss_machine(now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("running", &[5_000_800]), now);
        m
    }

    /// `(flag_id, igt_ms)` of every event_flag sent.
    fn sent_flag_igts(effects: &[Effect]) -> Vec<(u32, u32)> {
        sent_flag_details(effects)
            .into_iter()
            .map(|(flag, igt, _)| (flag, igt))
            .collect()
    }

    /// One scan as the shell performs it: `event_ids`, then the boss flags
    /// `boss_flags_to_read` names, those in `dead` reading set. Returns the
    /// boss flags read and the tick's effects.
    fn boss_scan(
        m: &mut RaceMachine,
        dead: &[u32],
        igt: u32,
        at: Instant,
    ) -> (Vec<u32>, Vec<Effect>) {
        let read: Vec<u32> = m.boss_flags_to_read().collect();
        let mut reads = vec![(100, false), (200, false), (900, false)];
        reads.extend(read.iter().map(|&flag| (flag, dead.contains(&flag))));
        let fx = m.tick(tick_in(snap(Some(igt), true), true, Some(reads)), at);
        (read, fx)
    }

    #[test]
    fn boss_flag_is_sent_at_once_and_never_cleared() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        let reads = vec![(100, false), (200, false), (900, false), (5_000_800, true)];

        // Sent in the same poll, not deferred to a loading exit, and left
        // set in game memory: clearing it would bring the boss back.
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, Some(reads.clone())),
            now + ms(150),
        );
        assert_eq!(sent_flag_igts(&fx), vec![(5_000_800, 60_000)]);
        assert!(!fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })));
        assert!(m.triggered_flags.contains(&5_000_800));

        // The flag still reads set: reported once.
        let fx = m.tick(
            tick_in(snap(Some(60_200), true), true, Some(reads)),
            now + ms(300),
        );
        assert!(sent_flags(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn boss_flags_to_read_skips_reported_kills() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        assert_eq!(m.boss_flags_to_read().collect::<Vec<_>>(), vec![5_000_800]);

        m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + ms(150),
        );
        assert_eq!(m.boss_flags_to_read().count(), 0);
    }

    #[test]
    fn boss_kill_buffered_while_disconnected_then_sent_on_reconnect() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(100),
        );
        let reads = vec![(100, false), (200, false), (900, false), (5_000_800, true)];

        // Killed while the connection is down: buffered, not sent.
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), false, Some(reads.clone())),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(m.flag_buffer.has_pending());

        // Reconnected, the flag still set: the kill goes out once, with the
        // IGT it was seen at.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(5),
        );
        let fx = m.tick(
            tick_in(snap(Some(65_000), true), true, Some(reads)),
            now + secs(5) + ms(10),
        );
        assert_eq!(sent_flag_igts(&fx), vec![(5_000_800, 60_000)]);
    }

    #[test]
    fn boss_flag_ignored_while_the_race_is_not_running() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("setup", &[5_000_800]), now);
        let reads = vec![(100, false), (200, false), (900, false), (5_000_800, true)];

        // Before the start: not read, and a set flag read anyway is not
        // sent, buffered or marked.
        assert_eq!(m.boss_flags_to_read().count(), 0);
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, Some(reads.clone())),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty());
        assert!(!m.flag_buffer.has_pending());
        assert!(!m.triggered_flags.contains(&5_000_800));

        // The race starts: the flag is read, and the next poll reports the
        // kill, once.
        m.handle_message(MachineMessage::RaceStart(0), now + secs(1));
        assert_eq!(m.boss_flags_to_read().collect::<Vec<_>>(), vec![5_000_800]);
        let fx = m.tick(
            tick_in(snap(Some(61_000), true), true, Some(reads.clone())),
            now + secs(1) + ms(150),
        );
        assert_eq!(sent_flag_igts(&fx), vec![(5_000_800, 61_000)]);
        let fx = m.tick(
            tick_in(snap(Some(61_200), true), true, Some(reads)),
            now + secs(1) + ms(300),
        );
        assert!(sent_flags(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn boss_flags_are_reported_again_after_a_save_reload() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(599_000), true), true, None), now + ms(10));
        let reads = vec![(100, false), (200, false), (900, false), (5_000_800, true)];
        let fx = m.tick(
            tick_in(snap(Some(600_000), true), true, Some(reads.clone())),
            now + ms(150),
        );
        assert_eq!(sent_flags(&fx), vec![5_000_800]);

        // A backup 200 s older, in which the boss is dead too: the per-save
        // flush forgets the report, the loading-exit scan makes it again
        // (the server keeps the first kill).
        m.tick(tick_in(snap(None, false), true, None), now + secs(5));
        m.tick(
            tick_in(snap(Some(400_000), false), true, None),
            now + secs(8),
        );
        let fx = m.tick(
            tick_in(snap(Some(400_100), true), true, Some(reads)),
            now + secs(9),
        );
        assert_eq!(sent_flag_igts(&fx), vec![(5_000_800, 400_100)]);
        assert!(!fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })));
    }

    #[test]
    fn restored_boss_kill_is_not_reported_again_by_the_next_scan() {
        // The defeat flag stays set in the save: the scan at the loading
        // exit sees it too, and must not report it a second time at the
        // later IGT.
        let now = Instant::now();
        let mut m = RaceMachine::new(1_000_000, String::new(), false, now);
        m.restore_unacked(unacked("p1", &[(5_000_800, 500_000, None)]));
        m.handle_message(auth_ok_with_bosses("running", &[5_000_800]), now);
        m.tick(tick_in(snap(None, false), true, None), now + ms(10));

        let fx = m.tick(
            tick_in(snap(Some(520_000), false), true, None),
            now + secs(10),
        );
        let fx2 = m.tick(
            tick_in(
                snap(Some(520_100), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + secs(11),
        );
        let sent: Vec<_> = sent_flag_igts(&fx)
            .into_iter()
            .chain(sent_flag_igts(&fx2))
            .collect();
        assert_eq!(sent, vec![(5_000_800, 500_000)]);
    }

    #[test]
    fn boss_kill_is_not_a_livesplit_arrival() {
        let now = Instant::now();
        let mut auth = ls_auth_ok("running", "playing", &[(1, 5_000)]);
        if let MachineMessage::AuthOk { seed, .. } = &mut auth {
            seed.boss_flags = vec![5_000_800];
        }
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth, now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + ms(150),
        );
        assert_eq!(sent_flags(&fx), vec![5_000_800]);
        assert!(run_views(&fx).is_empty(), "{fx:?}");
        assert_eq!(m.run_arrivals, vec![None, Some(5_000), None, None]);
    }

    #[test]
    fn boss_flags_are_not_read_after_the_runner_finishes() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        let mut me = m.race_state.participants[0].clone();
        me.status = ParticipantStatus::Finished;
        m.handle_message(MachineMessage::PlayerUpdate(me), now + ms(50));
        assert_eq!(m.boss_flags_to_read().count(), 0);

        // A set flag read anyway is neither sent, buffered nor marked.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty(), "{fx:?}");
        assert!(!m.flag_buffer.has_pending());
        assert!(!m.triggered_flags.contains(&5_000_800));
    }

    #[test]
    fn boss_flags_are_not_read_once_the_runner_is_out() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        let mut me = m.race_state.participants[0].clone();
        me.status = ParticipantStatus::Abandoned;
        m.handle_message(MachineMessage::PlayerUpdate(me), now + ms(50));
        assert_eq!(m.boss_flags_to_read().count(), 0);

        // A set flag read anyway is neither sent, buffered nor marked.
        let fx = m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + ms(150),
        );
        assert!(sent_flags(&fx).is_empty(), "{fx:?}");
        assert!(!m.flag_buffer.has_pending());
        assert!(!m.triggered_flags.contains(&5_000_800));
    }

    #[test]
    fn boss_kill_on_the_reconnect_frame_follows_the_in_flight_fog() {
        // The fog into the boss's node is still unacknowledged when the
        // connection drops. Its replay must reach the server before the
        // kill, which is otherwise dropped for want of a visit.
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        m.tick(
            tick_in(
                snap(Some(1_000), true),
                true,
                Some(vec![(100, true), (200, false), (900, false)]),
            ),
            now + ms(150),
        );
        m.tick(tick_in(snap(Some(1_000), false), true, None), now + ms(200));
        let fx = m.tick(
            tick_in(
                snap(Some(1_100), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            now + ms(400),
        );
        assert_eq!(sent_flags(&fx), vec![100]);
        let fog_id = sent_message_ids(&fx)[0];
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(500),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(2),
        );

        // The reconnect frame's poll finds the boss dead.
        let fx = m.tick(
            tick_in(
                snap(Some(30_000), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + secs(2) + ms(10),
        );
        let sent = sent_flag_details(&fx);
        assert_eq!(sent.len(), 2, "{fx:?}");
        assert_eq!((sent[0].0, sent[0].2), (100, fog_id));
        assert_eq!((sent[1].0, sent[1].1), (5_000_800, 30_000));
        let ready = fx
            .iter()
            .position(|e| matches!(e, Effect::SendReady))
            .expect("ready sent on the reconnect frame");
        let first_flag = fx
            .iter()
            .position(|e| matches!(e, Effect::SendEventFlag { .. }))
            .unwrap();
        assert!(ready < first_flag, "{fx:?}");
    }

    #[test]
    fn boss_kill_caught_by_the_reconnect_rescan_carries_the_held_igt() {
        let now = Instant::now();
        let mut m = running_boss_machine(now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));
        let (_, fx) = boss_scan(&mut m, &[], 60_000, now + ms(150));
        assert!(sent_flags(&fx).is_empty());
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(160),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + ms(170),
        );

        // Back within the poll interval, on a frame whose clock reads the
        // transient 0 of a reload: only the reconnect rescan reads the flags,
        // and the kill carries the last good IGT.
        let fx = m.tick(
            tick_in(
                snap(Some(0), true),
                true,
                Some(vec![
                    (100, false),
                    (200, false),
                    (900, false),
                    (5_000_800, true),
                ]),
            ),
            now + ms(180),
        );
        assert_eq!(sent_flag_igts(&fx), vec![(5_000_800, 60_000)]);
    }

    #[test]
    fn boss_flags_are_read_a_few_per_poll_in_rotation() {
        let now = Instant::now();
        let bosses: Vec<u32> = (0..20).map(|i| 5_000_800 + 10 * i).collect();
        assert!(bosses.len() > BOSS_FLAG_READS_PER_POLL);
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("running", &bosses), now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // The last boss is dead: outside the first window, it is caught
        // once its turn comes, and every flag is read within the bound.
        let dead = [bosses[19]];
        let polls = bosses.len().div_ceil(BOSS_FLAG_READS_PER_POLL) as u32;
        let mut seen = HashSet::new();
        let mut kills = Vec::new();
        for poll in 1..=polls {
            let (read, fx) = boss_scan(
                &mut m,
                &dead,
                60_000 + 100 * poll,
                now + ms(150 * poll as u64),
            );
            assert!(read.len() <= BOSS_FLAG_READS_PER_POLL, "{read:?}");
            if poll == 1 {
                assert!(!read.contains(&bosses[19]));
            }
            seen.extend(read);
            kills.extend(sent_flag_igts(&fx));
        }
        assert_eq!(seen, bosses.iter().copied().collect::<HashSet<_>>());
        assert_eq!(kills.len(), 1, "{kills:?}");
        assert_eq!(kills[0].0, bosses[19]);
    }

    #[test]
    fn unreadable_boss_flags_do_not_stall_the_rotation() {
        let now = Instant::now();
        let bosses: Vec<u32> = (0..20).map(|i| 5_000_800 + 10 * i).collect();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("running", &bosses), now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // The shell asks for the first window, and none of it is readable.
        let first: Vec<u32> = m.boss_flags_to_read().collect();
        assert_eq!(first, bosses[..8].to_vec());
        m.tick(
            tick_in(
                snap(Some(60_000), true),
                true,
                Some(vec![(100, false), (200, false), (900, false)]),
            ),
            now + ms(150),
        );

        // The next scan moves on, and catches a kill in the next window.
        let (read, fx) = boss_scan(&mut m, &[bosses[10]], 60_100, now + ms(300));
        assert_eq!(read, bosses[8..16].to_vec());
        assert_eq!(sent_flag_igts(&fx), vec![(bosses[10], 60_100)]);
    }

    #[test]
    fn a_kill_does_not_shift_the_next_boss_window() {
        // The kill reported during the scan must not move the rotation past
        // a flag the scan never read.
        let now = Instant::now();
        let bosses: Vec<u32> = (0..20).map(|i| 5_000_800 + 10 * i).collect();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("running", &bosses), now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        let (read, fx) = boss_scan(&mut m, &[bosses[0]], 60_000, now + ms(150));
        assert_eq!(read, bosses[..8].to_vec());
        assert_eq!(sent_flags(&fx), vec![bosses[0]]);
        let (read, _) = boss_scan(&mut m, &[bosses[0]], 60_100, now + ms(300));
        assert_eq!(read, bosses[8..16].to_vec());
    }

    #[test]
    fn reported_boss_flags_take_no_read_slot() {
        let now = Instant::now();
        let bosses: Vec<u32> = (0..10).map(|i| 5_000_800 + 10 * i).collect();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_bosses("running", &bosses), now);
        m.tick(tick_in(snap(Some(500), true), true, None), now + ms(10));

        // Two kills in the first window.
        let (read, fx) = boss_scan(&mut m, &bosses[..2], 60_000, now + ms(150));
        assert!(read.contains(&bosses[0]) && read.contains(&bosses[1]));
        assert_eq!(sent_flags(&fx), bosses[..2].to_vec());

        // The next windows hold only the 8 flags still unreported.
        let unreported: HashSet<u32> = bosses[2..].iter().copied().collect();
        for poll in 2..=3u64 {
            let (read, fx) = boss_scan(&mut m, &bosses[..2], 60_000, now + ms(150 * poll));
            assert_eq!(read.iter().copied().collect::<HashSet<_>>(), unreported);
            assert_eq!(read.len(), unreported.len());
            assert!(sent_flags(&fx).is_empty());
        }
    }

    // ------------------------------------------------------------------
    // Race items
    // ------------------------------------------------------------------

    /// The Race Item goods, its use and removal flags, and the Shield's
    /// goods and removal flag (no use flag).
    const RACE_ITEM_GOODS: u32 = 1_450_801;
    const USE_FLAG: u32 = 1_050_290_101;
    const REMOVE_FLAG: u32 = 1_050_290_201;
    const SHIELD_GOODS: u32 = 1_450_800;
    const SHIELD_REMOVE_FLAG: u32 = 1_050_290_200;
    const HAMMER_ICON: u16 = 60_390;

    /// auth_ok of `auth_ok` (flags [100, 200, 900], finish 900) for a race
    /// with `race_items` on or off, whose seed catalog holds the Race Item
    /// goods (use flag `USE_FLAG`), on which the Red Shell and the Hammer are
    /// held, and the Shield's own goods (no use flag).
    fn auth_ok_with_items(status: &str, race_items: bool) -> MachineMessage {
        let race: RaceInfo = serde_json::from_str(&format!(
            r#"{{"id":"r1","name":"x","status":"{status}","race_items":{race_items}}}"#
        ))
        .unwrap();
        let seed: SeedInfo = serde_json::from_str(
            r#"{"total_layers": 3, "event_ids": [100, 200, 900], "finish_event": 900,
                "death_flags": {}, "race_item_catalog": {
                  "goods": {
                    "race_item": {"goods_id": 1450801, "use_flag": 1050290101,
                                  "remove_flag": 1050290201, "icon_id": 60396},
                    "shield": {"goods_id": 1450800, "use_flag": null,
                               "remove_flag": 1050290200, "icon_id": 60385}},
                  "items": {
                    "red_shell": {"name": "Red Shell", "icon": "red_shell",
                                  "icon_id": 60388, "goods": "race_item"},
                    "hammer": {"name": "Hammer", "icon": "hammer",
                               "icon_id": 60390, "goods": "race_item"},
                    "shield": {"name": "Shield", "icon": "shield",
                               "icon_id": 60385, "goods": "shield"}}}}"#,
        )
        .unwrap();
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race,
            seed,
            participants: vec![test_participant("p1", "playing", 1)],
            phantom_skin: None,
            latest_mod_version: None,
            held_item: None,
            relay: None,
        }
    }

    /// The same auth_ok naming the item the server says the runner holds.
    fn holding(mut auth: MachineMessage, item: &str) -> MachineMessage {
        if let MachineMessage::AuthOk { held_item, .. } = &mut auth {
            *held_item = Some(item.to_string());
        }
        auth
    }

    /// Machine authed into a running race with items, past its first
    /// connected frame (`ready` sent), the player loaded.
    fn running_items_machine(now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(auth_ok_with_items("running", true), now);
        m.tick(tick_in(snap(Some(60_000), true), true, None), now + ms(10));
        m
    }

    /// One scan as the shell performs it: `event_ids` (unset), then the use
    /// flags `item_use_flags_to_read` names, those in `used` reading set.
    fn items_scan(m: &RaceMachine, used: &[u32]) -> Option<Vec<(u32, bool)>> {
        let mut reads = vec![(100, false), (200, false), (900, false)];
        reads.extend(
            m.item_use_flags_to_read()
                .map(|flag| (flag, used.contains(&flag))),
        );
        Some(reads)
    }

    fn wire_banner(icon: &str, title: &str) -> ItemBanner {
        ItemBanner {
            icon: icon.to_string(),
            title: title.to_string(),
            line: "line".to_string(),
            detail: "detail".to_string(),
        }
    }

    fn grant(grant_id: u64, item: &str) -> MachineMessage {
        MachineMessage::ItemGrant {
            grant_id,
            item: item.to_string(),
            banner: wire_banner(item, "Red Shell"),
        }
    }

    fn item_hit(effect: ItemEffectPayload, reminder: Option<(&str, u32)>) -> MachineMessage {
        MachineMessage::ItemEffect {
            item: "hammer".to_string(),
            effect,
            banner: Some(wire_banner("hammer", "Hammer")),
            reminder: reminder.map(|(text, duration_ms)| ItemReminder {
                text: text.to_string(),
                duration_ms,
            }),
        }
    }

    /// The race item effects of a batch, in order, event_flag sends included.
    fn item_steps(effects: &[Effect]) -> Vec<&'static str> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SendReady => Some("ready"),
                Effect::SendEventFlag { .. } => Some("flag"),
                Effect::ReportItemInventory { .. } => Some("report"),
                Effect::SetGoodsIcon { .. } => Some("icon"),
                Effect::SpawnRaceItem { .. } => Some("spawn"),
                Effect::SendItemReceived { .. } => Some("received"),
                Effect::ApplySpEffect { .. }
                | Effect::ApplyItemDamage { .. }
                | Effect::ApplyEquipLoad { .. } => Some("apply"),
                _ => None,
            })
            .collect()
    }

    fn banner_title(m: &RaceMachine) -> Option<(String, FeedTone)> {
        m.item_banner().map(|b| (b.title.clone(), b.tone))
    }

    #[test]
    fn use_flag_is_cleared_sent_at_once_and_can_fire_again() {
        let now = Instant::now();
        let mut m = running_items_machine(now);

        // Sent in the same poll, not deferred to a loading exit, and cleared
        // in game so the next use raises it again.
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, items_scan(&m, &[USE_FLAG])),
            now + ms(150),
        );
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: USE_FLAG,
            value: false,
        }));
        let first = sent_flag_details(&fx);
        assert_eq!(first.len(), 1, "{fx:?}");
        assert_eq!((first[0].0, first[0].1), (USE_FLAG, 60_000));
        assert!(!m.triggered_flags.contains(&USE_FLAG));
        assert!(!m.flag_buffer.has_deferred());

        // Cleared: the next poll reads it unset.
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            now + ms(300),
        );
        assert!(sent_flags(&fx).is_empty(), "{fx:?}");

        // The next use is a new event.
        let fx = m.tick(
            tick_in(snap(Some(90_000), true), true, items_scan(&m, &[USE_FLAG])),
            now + ms(450),
        );
        let again = sent_flag_details(&fx);
        assert_eq!(again.len(), 1, "{fx:?}");
        assert_eq!((again[0].0, again[0].1), (USE_FLAG, 90_000));
        assert_ne!(again[0].2, first[0].2);
    }

    #[test]
    fn use_flags_are_not_read_with_items_off() {
        let now = Instant::now();
        let mut off = RaceMachine::new(1, String::new(), false, now);
        off.handle_message(auth_ok_with_items("running", false), now);
        assert_eq!(off.item_use_flags_to_read().count(), 0);

        // The same catalog with items on: read while the race runs only.
        let mut setup = RaceMachine::new(1, String::new(), false, now);
        setup.handle_message(auth_ok_with_items("setup", true), now);
        assert_eq!(setup.item_use_flags_to_read().count(), 0);
        let on = running_items_machine(now);
        assert_eq!(on.item_use_flags_to_read().collect::<Vec<_>>(), [USE_FLAG]);
    }

    #[test]
    fn use_flag_found_at_load_is_reported_before_the_inventory() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        m.handle_message(grant(1, "red_shell"), now + ms(200));

        // Used just before a quit-out: the use reaches the server before the
        // inventory that no longer holds it, and the pending spawn, its icon
        // first, comes last. The use spent the held item: no icon before
        // the report.
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[USE_FLAG])),
            now + secs(1),
        );
        assert_eq!(
            item_steps(&fx),
            ["flag", "report", "icon", "spawn"],
            "{fx:?}"
        );
        assert_eq!(sent_flags(&fx), [USE_FLAG]);
    }

    #[test]
    fn grant_waits_for_the_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );

        let fx = m.handle_message(grant(1, "red_shell"), now + ms(200));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        // Sent again by a reconnection during the same load.
        let fx = m.handle_message(grant(1, "red_shell"), now + ms(300));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        let fx = m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(400),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert_eq!(banner_title(&m), None);

        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        let spawns: Vec<_> = fx
            .iter()
            .filter(|e| matches!(e, Effect::SpawnRaceItem { .. }))
            .collect();
        assert_eq!(
            spawns,
            [&Effect::SpawnRaceItem {
                grant_id: 1,
                goods_id: RACE_ITEM_GOODS,
            }]
        );
        // The banner waits for the goods to be in the inventory.
        assert_eq!(banner_title(&m), None);
        m.grant_spawn_result(1, true, now + secs(1));
        assert_eq!(
            banner_title(&m),
            Some(("RED SHELL".to_string(), FeedTone::Gain))
        );
    }

    #[test]
    fn a_shield_shows_a_held_row_until_it_leaves() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "shield"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(m.item_held(), None, "not before the goods are in");
        m.grant_spawn_result(1, true, now + ms(120));
        let held = m.item_held().expect("held row");
        assert_eq!(
            (held.key.as_str(), held.icon.as_str(), held.text.as_str()),
            ("shield", "shield", "Shield")
        );

        // Spent on a block: the server removes it.
        m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: Some(wire_banner("shield", "Shield")),
            },
            now + secs(2),
        );
        assert_eq!(m.item_held(), None);
    }

    #[test]
    fn the_held_row_ends_with_the_run() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(holding(auth_ok_with_items("running", true), "shield"), now);
        m.inventory_read(&["shield".to_string()]);
        assert!(m.item_held().is_some());
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "finished", 3)],
                leader_splits: None,
            },
            now + secs(1),
        );
        assert_eq!(
            m.item_held(),
            None,
            "an unspent Shield stops showing at the finish"
        );
    }

    #[test]
    fn the_held_row_follows_the_inventory_reads() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(holding(auth_ok_with_items("running", true), "shield"), now);
        // Shown while the held item's goods is in the inventory.
        m.inventory_read(&["shield".to_string()]);
        assert_eq!(m.item_held().map(|h| h.key.as_str()), Some("shield"));
        m.inventory_read(&["race_item".to_string()]);
        assert_eq!(
            m.item_held(),
            None,
            "another goods is no row of the held item"
        );
        m.inventory_read(&["shield".to_string()]);
        m.inventory_read(&[]);
        assert_eq!(m.item_held(), None);
        // Nothing held: no row, whatever the inventory holds.
        m.handle_message(auth_ok_with_items("running", true), now + ms(10));
        m.inventory_read(&["race_item".to_string(), "shield".to_string()]);
        assert_eq!(m.item_held(), None);
    }

    #[test]
    fn resent_grant_already_spawned_is_only_acknowledged() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(item_steps(&fx), ["icon", "spawn"]);
        m.grant_spawn_result(1, true, now + ms(120));
        m.tick(tick_in(snap(Some(67_000), true), true, None), now + secs(6));
        assert_eq!(banner_title(&m), None);

        // The server sends it again (item_received lost with a dropped
        // connection): acknowledged, neither spawned nor announced again.
        let fx = m.handle_message(grant(1, "red_shell"), now + secs(7));
        assert!(fx.contains(&Effect::SendItemReceived { grant_id: 1 }));
        assert_eq!(item_steps(&fx), ["received"]);
        let fx = m.tick(
            tick_in(snap(Some(68_000), true), true, None),
            now + secs(7) + ms(10),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert_eq!(banner_title(&m), None);
    }

    #[test]
    fn failed_spawn_is_retried_at_the_next_load_only() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(item_steps(&fx), ["icon", "spawn"]);
        m.grant_spawn_result(1, false, now + ms(120));
        assert_eq!(banner_title(&m), None);

        // Not on every frame of the same load.
        let fx = m.tick(tick_in(snap(Some(61_100), true), true, None), now + ms(200));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        // The server sends it again: neither acknowledged (no goods yet)
        // nor queued a second time.
        let fx = m.handle_message(grant(1, "red_shell"), now + ms(300));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        let fx = m.tick(tick_in(snap(Some(61_200), true), true, None), now + ms(400));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");

        // The next game load tries once more, after its report (the held
        // item's icon written before each).
        m.tick(
            tick_in(snap(Some(61_300), false), true, None),
            now + ms(500),
        );
        let fx = m.tick(
            tick_in(snap(Some(61_400), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(
            item_steps(&fx),
            ["icon", "report", "icon", "spawn"],
            "{fx:?}"
        );
        m.grant_spawn_result(1, true, now + secs(1));
        assert_eq!(
            banner_title(&m),
            Some(("RED SHELL".to_string(), FeedTone::Gain))
        );

        // Handled now: sent again, it is only acknowledged.
        let fx = m.handle_message(grant(1, "red_shell"), now + secs(2));
        assert_eq!(item_steps(&fx), ["received"]);
    }

    #[test]
    fn failed_spawn_is_retried_on_the_reconnect_frame() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, false, now + ms(120));

        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + secs(1),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(1) + ms(10),
        );
        let fx = m.tick(
            tick_in(snap(Some(62_000), true), true, items_scan(&m, &[])),
            now + secs(1) + ms(20),
        );
        assert_eq!(
            item_steps(&fx),
            ["ready", "icon", "report", "icon", "spawn"],
            "{fx:?}"
        );
    }

    #[test]
    fn auth_ok_of_a_race_with_items_prewarms_their_game_access() {
        let now = Instant::now();
        let mut on = RaceMachine::new(1, String::new(), false, now);
        let fx = on.handle_message(auth_ok_with_items("running", true), now);
        assert!(fx.contains(&Effect::PrewarmRaceItems), "{fx:?}");

        let mut off = RaceMachine::new(1, String::new(), false, now);
        let fx = off.handle_message(auth_ok_with_items("running", false), now);
        assert!(!fx.contains(&Effect::PrewarmRaceItems), "{fx:?}");
    }

    #[test]
    fn item_effect_waits_for_the_load_and_starts_its_timer_then() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        let hit = item_hit(
            ItemEffectPayload::Speffect {
                speffect_id: 1_450_827,
                duration_ms: None,
            },
            Some(("Fat-roll", 15_000)),
        );
        let fx = m.handle_message(hit, now + ms(200));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        let fx = m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + secs(3),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert_eq!(banner_title(&m), None);
        assert_eq!(m.item_reminders(now + secs(3)).count(), 0);

        let t1 = now + secs(5);
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            t1,
        );
        assert!(fx.contains(&Effect::ApplySpEffect {
            speffect_id: 1_450_827,
            left_ms: None,
        }));
        let rows: Vec<_> = m.item_reminders(t1).collect();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].0.text, "Fat-roll");
        assert_eq!(rows[0].0.tone, FeedTone::Malus);
        assert_eq!(rows[0].1, Some(secs(15)));
        assert_eq!(
            banner_title(&m),
            Some(("HAMMER".to_string(), FeedTone::Malus))
        );

        // The banner's time runs from the application too.
        let shown = ItemFeed::BANNER_DURATION;
        m.tick(
            tick_in(snap(Some(64_900), true), true, None),
            t1 + shown - ms(100),
        );
        assert!(banner_title(&m).is_some());
        m.tick(tick_in(snap(Some(65_000), true), true, None), t1 + shown);
        assert_eq!(banner_title(&m), None);
    }

    #[test]
    fn damage_effect_emits_apply_item_damage() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let hit = item_hit(
            ItemEffectPayload::Damage {
                base_pct: 20,
                floor_pct: 20,
                tail_pct: 5,
            },
            None,
        );
        m.handle_message(hit, now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(item_steps(&fx), ["apply"]);
        assert!(fx.contains(&Effect::ApplyItemDamage {
            base_pct: 20,
            floor_pct: 20,
            tail_pct: 5,
        }));
        assert_eq!(m.item_reminders(now + ms(120)).count(), 0);
    }

    #[test]
    fn equip_load_effect_emits_apply_equip_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let hit = item_hit(
            ItemEffectPayload::EquipLoad {
                speffect_id: 1_450_827,
                load_pct: 97,
                duration_ms: Some(15_000),
            },
            Some(("Fat-roll", 15_000)),
        );
        m.handle_message(hit, now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(item_steps(&fx), ["apply"]);
        assert!(fx.contains(&Effect::ApplyEquipLoad {
            speffect_id: 1_450_827,
            load_pct: 97,
            left_ms: Some(15_000),
        }));
        assert_eq!(m.item_reminders(now + ms(120)).count(), 1);
    }

    #[test]
    fn ink_effect_sets_the_ink_timer() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let hit = item_hit(
            ItemEffectPayload::Ink {
                duration_ms: 15_000,
            },
            Some(("Ink", 15_000)),
        );
        m.handle_message(hit, now + ms(100));
        assert!(!m.ink_active(now + ms(110)));

        let t1 = now + ms(120);
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert!(m.ink_active(t1));
        assert!(m.ink_active(t1 + ms(14_999)));
        assert!(!m.ink_active(t1 + secs(15)));
    }

    /// The server's zone_update with `unused_exits`.
    fn zone_update_with_exits(unused_exits: Option<u32>) -> MachineMessage {
        let mut msg = zone_update("Zone", None);
        if let MachineMessage::ZoneUpdate {
            unused_exits: count,
            ..
        } = &mut msg
        {
            *count = unused_exits;
        }
        msg
    }

    /// The server's zone_update with `unused_exits`, revealed by a loaded
    /// frame at `at`.
    fn reveal_zone(m: &mut RaceMachine, unused_exits: Option<u32>, igt: u32, at: Instant) {
        m.handle_message(zone_update_with_exits(unused_exits), at);
        m.tick(tick_in(snap(Some(igt), true), true, None), at + ms(10));
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().unused_exits,
            unused_exits
        );
    }

    fn ink_hit(m: &mut RaceMachine, at: Instant) {
        m.handle_message(
            item_hit(
                ItemEffectPayload::Ink {
                    duration_ms: 30_000,
                },
                Some(("Ink", 30_000)),
            ),
            at,
        );
    }

    fn ink_rows(m: &RaceMachine, at: Instant) -> Vec<(String, Option<Duration>)> {
        m.item_reminders(at)
            .map(|(row, left)| (row.text.clone(), left))
            .collect()
    }

    #[test]
    fn ink_waits_for_a_zone_with_unused_exits() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        reveal_zone(&mut m, Some(0), 61_000, now + ms(100));
        ink_hit(&mut m, now + ms(200));
        let t1 = now + ms(300);
        m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
        assert!(!m.ink_active(t1));
        assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), None)]);
        // Still pending a minute on: it never counted down.
        let t2 = t1 + secs(60);
        m.tick(tick_in(snap(Some(121_200), true), true, None), t2);
        assert!(!m.ink_active(t2));

        reveal_zone(&mut m, Some(2), 121_300, t2 + ms(100));
        let t3 = t2 + ms(110);
        assert!(m.ink_active(t3));
        let left = ink_rows(&m, t3)[0].1.unwrap();
        assert!(secs(30) - left < ms(50), "{left:?}");
        assert!(m.ink_active(t3 + ms(29_900)));
        assert!(!m.ink_active(t3 + secs(30)));
    }

    #[test]
    fn ink_starts_at_once_in_a_zone_with_unused_exits() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        reveal_zone(&mut m, Some(1), 61_000, now + ms(100));
        ink_hit(&mut m, now + ms(200));
        let t1 = now + ms(300);
        m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
        assert!(m.ink_active(t1));
        assert!(m.ink_active(t1 + ms(29_900)));
        assert!(!m.ink_active(t1 + secs(30)));
    }

    #[test]
    fn ink_starts_at_once_when_the_count_is_unknown() {
        for known_zone in [true, false] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            if known_zone {
                reveal_zone(&mut m, None, 61_000, now + ms(100));
            } else {
                assert!(m.race_state.current_zone.is_none());
            }
            ink_hit(&mut m, now + ms(200));
            let t1 = now + ms(300);
            m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
            assert!(m.ink_active(t1), "zone known: {known_zone}");
        }
    }

    #[test]
    fn a_pending_ink_goes_with_the_run() {
        for finished in [false, true] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            reveal_zone(&mut m, Some(0), 61_000, now + ms(100));
            ink_hit(&mut m, now + ms(200));
            let t1 = now + ms(300);
            m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
            assert_eq!(ink_rows(&m, t1).len(), 1);
            if finished {
                m.handle_message(
                    MachineMessage::LeaderboardUpdate {
                        participants: vec![test_participant("p1", "finished", 3)],
                        leader_splits: None,
                    },
                    t1 + ms(10),
                );
                m.tick(tick_in(snap(Some(61_300), true), true, None), t1 + ms(20));
            } else {
                // A reset: the room closes, the same runner comes back to a
                // race in setup, then the new start.
                m.handle_message(
                    MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
                    t1 + ms(5),
                );
                m.handle_message(
                    MachineMessage::StatusChanged(ConnectionStatus::Connected),
                    t1 + ms(6),
                );
                m.handle_message(auth_ok_with_items("setup", true), t1 + ms(7));
                m.handle_message(MachineMessage::RaceStart(0), t1 + ms(10));
            }
            assert!(ink_rows(&m, t1 + ms(30)).is_empty(), "finished: {finished}");
            reveal_zone(&mut m, Some(3), 61_400, t1 + ms(100));
            assert!(!m.ink_active(t1 + ms(120)), "finished: {finished}");
            assert!(
                ink_rows(&m, t1 + ms(120)).is_empty(),
                "finished: {finished}"
            );
        }
    }

    #[test]
    fn a_running_ink_does_not_count_down_during_a_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        ink_hit(&mut m, now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert!(m.ink_active(t1));
        m.tick(tick_in(snap(Some(66_000), true), true, None), t1 + secs(5));
        // A 2 minute load.
        load(&mut m, t1 + secs(5), secs(120), 66_000, true);
        let t2 = t1 + secs(126);
        m.tick(tick_in(snap(Some(67_000), true), true, None), t2);
        // 6 s played of 30.
        assert!(m.ink_active(t2 + secs(23)));
        assert!(!m.ink_active(t2 + secs(25)));
    }

    /// From a zone with unused exits, an Ink received during a load and
    /// applied on its loading exit frame (whose `position`, when given,
    /// sends a zone query): it waits, the zone it came from no longer
    /// decides. The exit's effects and time.
    fn ink_during_a_load(
        m: &mut RaceMachine,
        now: Instant,
        position: bool,
    ) -> (Vec<Effect>, Instant) {
        reveal_zone(m, Some(2), 61_000, now + ms(100));
        let start = now + secs(1);
        m.tick(tick_in(snap(Some(62_000), false), true, None), start);
        ink_hit(m, start + secs(1));
        let mut input = tick_in(snap(Some(62_000), true), true, items_scan(m, &[]));
        if position {
            input.position = Some(PlayerPosition {
                map_id: 0x0A000000,
                map_id_str: "m10_00_00_00".to_string(),
                x: 1.0,
                y: 2.0,
                z: 3.0,
                play_region_id: None,
            });
        }
        let exit = start + secs(2);
        let fx = m.tick(input, exit);
        assert!(!m.ink_active(exit));
        assert_eq!(ink_rows(m, exit), [("Ink".to_string(), None)]);
        (fx, exit)
    }

    #[test]
    fn an_ink_applied_at_a_loading_exit_waits_for_the_next_reveal() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let (_, exit) = ink_during_a_load(&mut m, now, false);
        // The fog gate led into a two-gate arena: it still waits.
        reveal_zone(&mut m, Some(0), 62_100, exit + ms(100));
        let t1 = exit + ms(110);
        assert!(!m.ink_active(t1));
        assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), None)]);
        // On into a zone with an unused exit: 30 s from its reveal.
        reveal_zone(&mut m, Some(1), 70_000, exit + secs(8));
        let t2 = exit + secs(8) + ms(10);
        assert_eq!(ink_rows(&m, t2), [("Ink".to_string(), Some(secs(30)))]);
        assert!(m.ink_active(t2 + ms(29_900)));
        assert!(!m.ink_active(t2 + secs(30)));
    }

    #[test]
    fn an_ink_applied_at_a_reload_starts_when_the_zone_comes_back() {
        // A death or a quit-out reload: the server sends the same zone again.
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let (_, exit) = ink_during_a_load(&mut m, now, false);
        reveal_zone(&mut m, Some(2), 62_100, exit + ms(100));
        let t1 = exit + ms(110);
        assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), Some(secs(30)))]);
    }

    #[test]
    fn an_ink_applied_at_a_loading_exit_starts_on_an_unresolved_zone_query() {
        // No zone_update comes for an unresolved zone query: its ack lets
        // the current zone decide.
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let (fx, exit) = ink_during_a_load(&mut m, now, true);
        let message_id = fx
            .iter()
            .find_map(|e| match e {
                Effect::SendZoneQuery { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .expect("a zone query at the loading exit");
        let t1 = exit + ms(100);
        m.handle_message(MachineMessage::ZoneQueryAck { message_id }, t1);
        assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), Some(secs(30)))]);
    }

    const ARENA_BOSS: u32 = 5_000_800;
    const OTHER_BOSS: u32 = 5_000_801;

    /// `running_items_machine` whose seed names two boss defeat flags.
    fn running_items_boss_machine(now: Instant) -> RaceMachine {
        let mut m = running_items_machine(now);
        m.boss_flags = vec![ARENA_BOSS, OTHER_BOSS];
        m
    }

    /// The boss arena of `ARENA_BOSS` (with `unused_exits`), revealed by a
    /// loaded frame at `at`.
    fn reveal_arena(m: &mut RaceMachine, unused_exits: Option<u32>, igt: u32, at: Instant) {
        let mut msg = zone_update_with_exits(unused_exits);
        if let MachineMessage::ZoneUpdate { defeat_flag, .. } = &mut msg {
            *defeat_flag = Some(ARENA_BOSS);
        }
        m.handle_message(msg, at);
        m.tick(tick_in(snap(Some(igt), true), true, None), at + ms(10));
        assert_eq!(
            m.race_state.current_zone.as_ref().unwrap().defeat_flag,
            Some(ARENA_BOSS)
        );
    }

    #[test]
    fn ink_in_a_live_boss_arena_hides_the_exits_and_runs_from_the_kill() {
        // An arena with an unused exit (or a count unknown): the exits are
        // hidden through the fight, the time held whole until the kill.
        for unused_exits in [Some(2), None] {
            let now = Instant::now();
            let mut m = running_items_boss_machine(now);
            reveal_arena(&mut m, unused_exits, 61_000, now + ms(100));
            ink_hit(&mut m, now + ms(200));
            let t1 = now + ms(300);
            m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
            assert!(m.ink_active(t1), "{unused_exits:?}");

            // A long fight, and another boss's flag read set (a kill
            // scanned again after a save reload): still held, its 30 s whole.
            let t2 = t1 + secs(90);
            boss_scan(&mut m, &[OTHER_BOSS], 151_200, t2);
            assert!(m.triggered_flags.contains(&OTHER_BOSS));
            assert!(m.ink_active(t2), "{unused_exits:?}");
            assert_eq!(
                ink_rows(&m, t2),
                [("Ink".to_string(), Some(secs(30)))],
                "{unused_exits:?}"
            );

            let t3 = t2 + secs(5);
            boss_scan(&mut m, &[ARENA_BOSS], 156_200, t3);
            assert!(m.ink_active(t3 + ms(29_900)), "{unused_exits:?}");
            assert!(!m.ink_active(t3 + secs(30)), "{unused_exits:?}");
        }
    }

    #[test]
    fn ink_in_a_boss_arena_without_unused_exits_waits_through_the_kill() {
        // Every fog leads on: hiding them costs nothing, the kill included.
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_arena(&mut m, Some(0), 61_000, now + ms(100));
        ink_hit(&mut m, now + ms(200));
        let t1 = now + ms(300);
        m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
        assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), None)]);
        boss_scan(&mut m, &[ARENA_BOSS], 70_000, t1 + secs(10));
        assert!(!m.ink_active(t1 + secs(10)));
        assert_eq!(ink_rows(&m, t1 + secs(10)), [("Ink".to_string(), None)]);
    }

    #[test]
    fn ink_in_a_boss_arena_whose_boss_is_dead_starts_at_once() {
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_arena(&mut m, Some(2), 61_000, now + ms(100));
        boss_scan(&mut m, &[ARENA_BOSS], 61_100, now + ms(150));
        ink_hit(&mut m, now + ms(200));
        let t1 = now + ms(300);
        m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
        assert!(m.ink_active(t1 + ms(29_800)));
        assert!(!m.ink_active(t1 + secs(30)));
    }

    #[test]
    fn a_held_ink_follows_the_zone_its_runner_reaches_without_the_kill() {
        // Out of the arena with the boss alive (a death, a respawn at a
        // grace elsewhere): the zone revealed decides.
        for (unused_exits, runs) in [(Some(3), true), (Some(0), false)] {
            let now = Instant::now();
            let mut m = running_items_boss_machine(now);
            reveal_arena(&mut m, Some(2), 61_000, now + ms(100));
            ink_hit(&mut m, now + ms(200));
            m.tick(tick_in(snap(Some(61_200), true), true, None), now + ms(300));
            reveal_zone(&mut m, unused_exits, 70_000, now + secs(10));
            let t1 = now + secs(10) + ms(10);
            if runs {
                assert!(m.ink_active(t1 + ms(29_900)));
                assert!(!m.ink_active(t1 + secs(30)));
            } else {
                // Its exits readable again, the time still whole.
                assert_eq!(ink_rows(&m, t1), [("Ink".to_string(), None)]);
            }
        }
    }

    #[test]
    fn a_running_ink_keeps_its_end_through_reveals_and_a_kill() {
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_zone(&mut m, Some(2), 61_000, now + ms(100));
        ink_hit(&mut m, now + ms(200));
        let t1 = now + ms(300);
        m.tick(tick_in(snap(Some(61_200), true), true, None), t1);
        assert!(m.ink_active(t1));
        // A fog gate into a zone with unused exits, then into a live arena
        // whose boss dies: each may settle an ink not run yet, none touches
        // this one.
        reveal_zone(&mut m, Some(3), 62_000, t1 + secs(2));
        reveal_arena(&mut m, Some(2), 63_000, t1 + secs(4));
        boss_scan(&mut m, &[ARENA_BOSS], 64_000, t1 + secs(10));
        assert!(m.ink_active(t1 + ms(29_900)));
        assert!(!m.ink_active(t1 + secs(30)));
    }

    #[test]
    fn an_unresolved_zone_query_in_a_live_boss_arena_holds_the_ink() {
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_arena(&mut m, Some(2), 61_000, now + ms(100));
        // A death reload in the arena: the Ink lands on its loading exit,
        // whose zone query the server cannot resolve.
        let start = now + secs(1);
        m.tick(tick_in(snap(Some(62_000), false), true, None), start);
        ink_hit(&mut m, start + secs(1));
        let mut input = tick_in(snap(Some(62_000), true), true, items_scan(&m, &[]));
        input.position = Some(PlayerPosition {
            map_id: 0x0A000000,
            map_id_str: "m10_00_00_00".to_string(),
            x: 1.0,
            y: 2.0,
            z: 3.0,
            play_region_id: None,
        });
        let exit = start + secs(2);
        let fx = m.tick(input, exit);
        assert_eq!(ink_rows(&m, exit), [("Ink".to_string(), None)]);
        let message_id = fx
            .iter()
            .find_map(|e| match e {
                Effect::SendZoneQuery { message_id, .. } => Some(*message_id),
                _ => None,
            })
            .expect("a zone query at the loading exit");
        m.handle_message(MachineMessage::ZoneQueryAck { message_id }, exit + ms(100));
        assert!(m.ink_active(exit + ms(100)));
        assert_eq!(
            ink_rows(&m, exit + secs(60)),
            [("Ink".to_string(), Some(secs(30)))]
        );
    }

    #[test]
    fn a_kill_read_while_another_zone_is_coming_keeps_the_ink_held() {
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_arena(&mut m, Some(2), 61_000, now + ms(100));
        ink_hit(&mut m, now + ms(200));
        m.tick(tick_in(snap(Some(61_200), true), true, None), now + ms(300));
        // Through a gate (the arena's boss flag read late): the next zone
        // decides, not the kill.
        m.handle_message(zone_update_with_exits(Some(0)), now + secs(5));
        let mut reads = vec![(100, false), (200, false), (900, false)];
        reads.extend(m.boss_flags_to_read().map(|f| (f, f == ARENA_BOSS)));
        m.tick(
            tick_in(snap_load(Some(66_000), true, Some(true)), true, Some(reads)),
            now + secs(6),
        );
        assert!(m.triggered_flags.contains(&ARENA_BOSS));
        assert!(m.pending_zone_update.is_some());
        assert_eq!(
            ink_rows(&m, now + secs(40)),
            [("Ink".to_string(), Some(secs(30)))]
        );
    }

    #[test]
    fn a_pending_ink_starts_back_in_an_arena_whose_boss_is_dead() {
        // Killed, left by a gate into a zone with no unused exit, then back:
        // the reveal of the cleared arena runs it.
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_arena(&mut m, Some(2), 61_000, now + ms(100));
        boss_scan(&mut m, &[ARENA_BOSS], 61_100, now + ms(150));
        reveal_zone(&mut m, Some(0), 62_000, now + secs(2));
        ink_hit(&mut m, now + secs(3));
        let t1 = now + secs(3) + ms(100);
        m.tick(tick_in(snap(Some(63_200), true), true, None), t1);
        assert!(!m.ink_active(t1));
        reveal_arena(&mut m, Some(2), 70_000, now + secs(10));
        let t2 = now + secs(10) + ms(10);
        assert!(m.ink_active(t2 + ms(29_900)));
        assert!(!m.ink_active(t2 + secs(30)));
    }

    #[test]
    fn an_ink_hit_with_a_reveal_pending_follows_the_zone_to_come() {
        for (current, coming, starts) in [(Some(2), Some(0), false), (Some(0), Some(3), true)] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            reveal_zone(&mut m, current, 61_000, now + ms(100));
            // The next zone's update is in, its reveal waits for the fade
            // to clear.
            m.handle_message(zone_update_with_exits(coming), now + ms(200));
            ink_hit(&mut m, now + ms(300));
            let t1 = now + ms(320);
            m.tick(
                tick_in(snap_load(Some(61_300), true, Some(true)), true, None),
                t1,
            );
            assert!(m.pending_zone_update.is_some(), "coming: {coming:?}");
            assert_eq!(m.ink_active(t1), starts, "coming: {coming:?}");
            assert_eq!(ink_rows(&m, t1).len(), 1, "coming: {coming:?}");
        }
    }

    #[test]
    fn an_ink_hit_while_a_live_arena_is_coming_holds_it() {
        let now = Instant::now();
        let mut m = running_items_boss_machine(now);
        reveal_zone(&mut m, Some(0), 61_000, now + ms(100));
        // The arena's update is in (unused exits, its boss alive), its
        // reveal waits for the fade to clear: the arena decides.
        let mut coming = zone_update_with_exits(Some(2));
        if let MachineMessage::ZoneUpdate { defeat_flag, .. } = &mut coming {
            *defeat_flag = Some(ARENA_BOSS);
        }
        m.handle_message(coming, now + ms(200));
        ink_hit(&mut m, now + ms(300));
        let t1 = now + ms(320);
        m.tick(
            tick_in(snap_load(Some(61_300), true, Some(true)), true, None),
            t1,
        );
        assert!(m.pending_zone_update.is_some());
        assert!(m.ink_active(t1));
        assert_eq!(
            ink_rows(&m, t1 + secs(60)),
            [("Ink".to_string(), Some(secs(30)))]
        );
    }

    /// The spawn requests of a batch, by goods id.
    fn spawned_goods(effects: &[Effect]) -> Vec<u32> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::SpawnRaceItem { goods_id, .. } => Some(*goods_id),
                _ => None,
            })
            .collect()
    }

    /// A game load: an unloaded frame, then the loading exit's batch.
    fn items_load(m: &mut RaceMachine, at: Instant) -> Vec<Effect> {
        m.tick(tick_in(snap(Some(62_000), false), true, None), at);
        let scan = items_scan(m, &[]);
        m.tick(tick_in(snap(Some(62_100), true), true, scan), at + ms(500))
    }

    #[test]
    fn a_removed_goods_takes_its_failed_grant_with_it() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "shield"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(spawned_goods(&fx), [SHIELD_GOODS]);
        m.grant_spawn_result(1, false, now + ms(120));

        // The server spent the Shield (it blocked a hit) before the goods
        // ever spawned: the next load must not bring it back.
        m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: None,
            },
            now + ms(200),
        );
        let fx = items_load(&mut m, now + secs(1));
        assert!(spawned_goods(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn a_removed_goods_takes_its_grant_not_spawned_yet() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // Both arrive before the frame that would spawn it (a load).
        m.handle_message(grant(1, "shield"), now + ms(100));
        m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: None,
            },
            now + ms(110),
        );
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert!(spawned_goods(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn an_auth_keeps_only_the_queued_grant_of_the_item_held() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "shield"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, false, now + ms(120));

        // Still held on the server: the reconnection tries the spawn again.
        m.handle_message(
            holding(auth_ok_with_items("running", true), "shield"),
            now + secs(1),
        );
        let fx = items_load(&mut m, now + secs(2));
        assert_eq!(spawned_goods(&fx), [SHIELD_GOODS]);
        m.grant_spawn_result(1, false, now + secs(3));

        // Spent while the mod was offline (its `item_remove` lost): the
        // server names no held item, and the Shield never spawns.
        m.handle_message(auth_ok_with_items("running", true), now + secs(4));
        let fx = items_load(&mut m, now + secs(5));
        assert!(spawned_goods(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn a_spawn_never_answered_is_retried_at_the_next_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(spawned_goods(&fx), [RACE_ITEM_GOODS]);

        // The shell lost that batch: no `grant_spawn_result` ever comes.
        let fx = m.tick(tick_in(snap(Some(61_100), true), true, None), now + ms(200));
        assert!(spawned_goods(&fx).is_empty(), "{fx:?}");
        let fx = items_load(&mut m, now + secs(1));
        assert_eq!(spawned_goods(&fx), [RACE_ITEM_GOODS]);
    }

    #[test]
    fn a_removed_goods_keeps_the_grant_of_another_goods() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, false, now + ms(120));

        // A stray Shield taken back says nothing of the Race Item.
        m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: None,
            },
            now + ms(200),
        );
        let fx = items_load(&mut m, now + secs(1));
        assert_eq!(spawned_goods(&fx), [RACE_ITEM_GOODS]);
    }

    #[test]
    fn a_newer_grant_drops_the_ones_still_queued() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "shield"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, false, now + ms(120));

        // The server only grants to a runner holding nothing: grant 1 is
        // gone on its side (spent, lost), whatever message said so.
        m.handle_message(grant(2, "red_shell"), now + ms(200));
        let fx = items_load(&mut m, now + secs(1));
        assert_eq!(spawned_goods(&fx), [RACE_ITEM_GOODS]);
        m.grant_spawn_result(2, true, now + secs(2));
        assert_eq!(m.item_held().map(|row| row.key.as_str()), Some("red_shell"));
    }

    #[test]
    fn item_remove_raises_the_removal_flag_and_never_clears_it() {
        let now = Instant::now();
        let mut m = running_items_machine(now);

        // A shield that blocked a hit: raised at once, banner shown.
        let fx = m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: Some(wire_banner("shield", "Shield")),
            },
            now + ms(100),
        );
        let writes: Vec<_> = fx
            .iter()
            .filter(|e| matches!(e, Effect::SetGameFlag { .. }))
            .collect();
        assert_eq!(
            writes,
            [&Effect::SetGameFlag {
                flag_id: SHIELD_REMOVE_FLAG,
                value: true,
            }]
        );
        assert_eq!(
            banner_title(&m),
            Some(("SHIELD".to_string(), FeedTone::Gain))
        );

        // The game's event clears it: the mod never reads it, so never
        // clears it either.
        assert!(!m
            .item_use_flags_to_read()
            .any(|flag| flag == SHIELD_REMOVE_FLAG || flag == REMOVE_FLAG));
        let fx = m.tick(
            tick_in(snap(Some(61_000), true), true, items_scan(&m, &[])),
            now + ms(150),
        );
        assert!(
            !fx.iter()
                .any(|e| matches!(e, Effect::SetGameFlag { value: false, .. })),
            "{fx:?}"
        );

        // A take-back without a banner raises the flag alone.
        let fx = m.handle_message(
            MachineMessage::ItemRemove {
                goods: "race_item".to_string(),
                banner: None,
            },
            now + ms(200),
        );
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: REMOVE_FLAG,
            value: true,
        }));
    }

    #[test]
    fn inventory_report_waits_for_a_connection() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // A use the server has not acknowledged when the connection drops.
        let fx = m.tick(
            tick_in(snap(Some(60_000), true), true, items_scan(&m, &[USE_FLAG])),
            now + ms(150),
        );
        let in_flight = sent_message_ids(&fx);
        assert_eq!(in_flight.len(), 1, "{fx:?}");
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + ms(160),
        );
        m.tick(
            tick_in(snap(Some(60_000), false), false, None),
            now + ms(200),
        );

        // The load ends while disconnected, the item used before the
        // quit-out: the use is cleared and buffered, nothing reported.
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), false, items_scan(&m, &[USE_FLAG])),
            now + secs(1),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: USE_FLAG,
            value: false,
        }));
        let fx = m.tick(
            tick_in(snap(Some(61_000), true), false, None),
            now + secs(2),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");

        // The reconnect frame: ready, the replayed use, the buffered one,
        // then the report.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(3),
        );
        let fx = m.tick(
            tick_in(snap(Some(63_000), true), true, items_scan(&m, &[])),
            now + secs(3) + ms(10),
        );
        assert_eq!(
            item_steps(&fx),
            ["ready", "flag", "flag", "report"],
            "{fx:?}"
        );
        let sent = sent_flag_details(&fx);
        assert_eq!(
            (sent[0].0, sent[0].1, sent[0].2),
            (USE_FLAG, 60_000, in_flight[0])
        );
        assert_eq!((sent[1].0, sent[1].1), (USE_FLAG, 60_100));
        let report = fx.iter().find_map(|e| match e {
            Effect::ReportItemInventory { goods } => Some(goods.clone()),
            _ => None,
        });
        assert_eq!(
            report,
            Some(vec![
                ("race_item".to_string(), RACE_ITEM_GOODS),
                ("shield".to_string(), SHIELD_GOODS),
            ])
        );

        // Once per connection: the next frames report nothing.
        let fx = m.tick(
            tick_in(snap(Some(63_200), true), true, items_scan(&m, &[])),
            now + secs(3) + ms(200),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn item_result_shows_its_banner_and_reminder_at_once() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // Even during a load: the sender's outcome needs no game access.
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        let fx = m.handle_message(
            MachineMessage::ItemResult {
                item: "mushroom".to_string(),
                banner: wire_banner("mushroom", "Mushroom"),
                reminder: Some(ItemReminder {
                    text: "Infinite stamina".to_string(),
                    duration_ms: 15_000,
                }),
            },
            now + ms(200),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert_eq!(
            banner_title(&m),
            Some(("MUSHROOM".to_string(), FeedTone::Gain))
        );
        let rows: Vec<_> = m.item_reminders(now + ms(200)).collect();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].0.tone, FeedTone::Gain);
        assert_eq!(rows[0].1, Some(secs(15)));
    }

    #[test]
    fn auth_as_another_participant_drops_the_pending_items() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        m.handle_message(grant(1, "red_shell"), now + ms(200));
        m.handle_message(
            item_hit(
                ItemEffectPayload::Ink {
                    duration_ms: 15_000,
                },
                None,
            ),
            now + ms(300),
        );
        m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: Some(wire_banner("shield", "Shield")),
            },
            now + ms(400),
        );

        // A reconnection as the same runner keeps them.
        m.handle_message(auth_ok_with_items("running", true), now + ms(500));
        assert!(banner_title(&m).is_some());

        let mut other = auth_ok_with_items("running", true);
        if let MachineMessage::AuthOk {
            participant_id,
            participants,
            ..
        } = &mut other
        {
            *participant_id = "p2".to_string();
            participants[0] = test_participant("p2", "playing", 1);
        }
        m.handle_message(other, now + ms(600));
        assert_eq!(banner_title(&m), None);
        // Its load: the report, without the first runner's grant, effect
        // or held item's icon.
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");
        assert!(!m.ink_active(now + secs(1)));
    }

    #[test]
    fn a_race_reset_drops_the_race_items_of_the_voided_run() {
        // A reset closes the room: the mod authenticates again as the same
        // runner, the race in setup, and the new start comes before any
        // frame. Nothing queued for the voided run reaches the new attempt.
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // A spawn that failed, waiting for the next load.
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, false, now + ms(120));
        // An ink running and the sender's own reminder.
        m.handle_message(
            item_hit(
                ItemEffectPayload::Ink {
                    duration_ms: 15_000,
                },
                Some(("Ink", 15_000)),
            ),
            now + ms(200),
        );
        m.tick(tick_in(snap(Some(61_100), true), true, None), now + ms(220));
        m.handle_message(
            MachineMessage::ItemResult {
                item: "mushroom".to_string(),
                banner: wire_banner("mushroom", "Mushroom"),
                reminder: Some(ItemReminder {
                    text: "Infinite stamina".to_string(),
                    duration_ms: 15_000,
                }),
            },
            now + ms(300),
        );
        assert!(m.ink_active(now + ms(300)));
        assert_eq!(m.item_reminders(now + ms(300)).count(), 2);
        // A load: a grant and an effect wait for its end.
        m.tick(
            tick_in(snap(Some(62_000), false), true, None),
            now + ms(400),
        );
        m.handle_message(grant(2, "red_shell"), now + ms(500));
        m.handle_message(
            item_hit(
                ItemEffectPayload::Speffect {
                    speffect_id: 1_450_827,
                    duration_ms: None,
                },
                Some(("Fat-roll", 15_000)),
            ),
            now + ms(600),
        );

        let reset = now + secs(1);
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            reset,
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            reset + ms(10),
        );
        // Even an auth_ok still naming the voided run's item: the new start
        // forgets it (no icon written for it).
        m.handle_message(
            holding(auth_ok_with_items("setup", true), "red_shell"),
            reset + ms(20),
        );
        m.handle_message(MachineMessage::RaceStart(0), reset + ms(30));
        assert!(!m.ink_active(reset + ms(30)));
        assert_eq!(m.item_reminders(reset + ms(30)).count(), 0);

        // The new attempt's first loaded frame: its report, nothing else.
        let fx = m.tick(
            tick_in(snap(Some(300), true), true, items_scan(&m, &[])),
            reset + secs(5),
        );
        assert_eq!(item_steps(&fx), ["ready", "report"], "{fx:?}");
        let fx = m.tick(
            tick_in(snap(Some(1_000), false), true, None),
            reset + secs(6),
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        let fx = m.tick(
            tick_in(snap(Some(1_100), true), true, items_scan(&m, &[])),
            reset + secs(7),
        );
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");
    }

    #[test]
    fn race_items_waiting_when_the_run_ends_are_dropped() {
        // The runner finishes or is put out while a grant and an effect
        // wait for the load: neither reaches the game, then or later.
        for status in ["finished", "disqualified"] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            m.tick(
                tick_in(snap(Some(60_000), false), true, None),
                now + ms(100),
            );
            m.handle_message(grant(1, "red_shell"), now + ms(200));
            m.handle_message(
                item_hit(
                    ItemEffectPayload::Damage {
                        base_pct: 20,
                        floor_pct: 20,
                        tail_pct: 5,
                    },
                    Some(("Hit", 15_000)),
                ),
                now + ms(300),
            );
            m.handle_message(
                MachineMessage::LeaderboardUpdate {
                    participants: vec![test_participant("p1", status, 3)],
                    leader_splits: None,
                },
                now + ms(400),
            );
            let mut fx = m.tick(
                tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
                now + secs(1),
            );
            assert_eq!(banner_title(&m), None, "{status}");
            assert_eq!(m.item_reminders(now + secs(1)).count(), 0, "{status}");
            // Not kept for a later load either.
            fx.extend(m.tick(
                tick_in(snap(Some(60_200), false), true, None),
                now + secs(2),
            ));
            fx.extend(m.tick(
                tick_in(snap(Some(60_300), true), true, items_scan(&m, &[])),
                now + secs(3),
            ));
            assert!(item_steps(&fx).is_empty(), "{status}: {fx:?}");
        }
    }

    #[test]
    fn unknown_item_or_effect_kind_is_dropped() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let mut fx = m.handle_message(grant(1, "boo"), now + ms(100));
        fx.extend(m.handle_message(item_hit(ItemEffectPayload::Unknown, None), now + ms(110)));
        fx.extend(m.handle_message(
            MachineMessage::ItemRemove {
                goods: "boo".to_string(),
                banner: Some(wire_banner("boo", "Boo")),
            },
            now + ms(120),
        ));
        fx.extend(m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(150)));
        // No `item_received` either: the server sends the grant again at the
        // next auth.
        assert!(
            !fx.iter()
                .any(|e| matches!(e, Effect::SendItemReceived { .. })),
            "{fx:?}"
        );
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert!(
            !fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })),
            "{fx:?}"
        );
        assert_eq!(banner_title(&m), None);
    }

    #[test]
    fn outdated_pack_spawns_applies_and_reports_nothing() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, "seed-a".to_string(), false, now);
        let mut auth = auth_ok_with_items("running", true);
        if let MachineMessage::AuthOk { seed, .. } = &mut auth {
            seed.seed_id = Some("seed-a".to_string());
        }
        m.handle_message(auth, now);
        m.tick(tick_in(snap(Some(60_000), true), true, None), now + ms(10));
        m.handle_message(grant(1, "red_shell"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(60_100), true), true, None), now + ms(150));
        assert_eq!(item_steps(&fx), ["icon", "spawn"]);
        m.grant_spawn_result(1, true, now + ms(150));

        // A reroll: the loaded pack is outdated, its regulation may lack the
        // race goods.
        let race = |seed_id: &str| -> RaceInfo {
            serde_json::from_str(&format!(
                r#"{{"id":"r1","name":"x","status":"running","race_items":true,
                     "seed_id":"{seed_id}"}}"#
            ))
            .unwrap()
        };
        m.handle_message(
            MachineMessage::RaceInfoUpdate(race("seed-b")),
            now + ms(200),
        );
        assert!(m.seed_mismatch);

        // The spawned grant sent again, a new one, an effect, then a game
        // load and a reconnection: nothing reaches the game or the server.
        let mut fx = m.handle_message(grant(1, "red_shell"), now + ms(300));
        fx.extend(m.handle_message(grant(2, "red_shell"), now + ms(310)));
        fx.extend(m.handle_message(
            item_hit(
                ItemEffectPayload::Speffect {
                    speffect_id: 1_450_827,
                    duration_ms: None,
                },
                Some(("Fat-roll", 15_000)),
            ),
            now + ms(320),
        ));
        fx.extend(m.tick(
            tick_in(snap(Some(60_200), false), true, None),
            now + ms(400),
        ));
        fx.extend(m.tick(
            tick_in(snap(Some(60_300), true), true, items_scan(&m, &[])),
            now + secs(1),
        ));
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            now + secs(2),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            now + secs(2) + ms(10),
        );
        fx.extend(m.tick(
            tick_in(snap(Some(61_300), true), true, items_scan(&m, &[])),
            now + secs(2) + ms(20),
        ));
        assert_eq!(item_steps(&fx), ["ready"], "{fx:?}");
        assert_eq!(m.item_reminders(now + secs(2) + ms(20)).count(), 0);

        // Held, not dropped: a current pack handles them.
        m.handle_message(
            MachineMessage::RaceInfoUpdate(race("seed-a")),
            now + secs(3),
        );
        let fx = m.tick(
            tick_in(snap(Some(62_300), true), true, None),
            now + secs(3) + ms(10),
        );
        assert_eq!(item_steps(&fx), ["icon", "spawn", "apply"], "{fx:?}");
    }

    #[test]
    fn a_wrong_save_gets_no_race_item_write() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // Another, further-along save is loaded.
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        let mut fx = m.tick(
            tick_in(snap(Some(500_000), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert!(m.wrong_save);

        fx.extend(m.handle_message(grant(1, "red_shell"), now + secs(2)));
        fx.extend(m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: Some(wire_banner("shield", "Shield")),
            },
            now + secs(2),
        ));
        fx.extend(m.tick(
            tick_in(snap(Some(500_100), true), true, None),
            now + secs(3),
        ));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        assert!(
            !fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })),
            "{fx:?}"
        );
        // The banner still tells the runner what happened.
        assert_eq!(
            banner_title(&m),
            Some(("SHIELD".to_string(), FeedTone::Gain))
        );

        // The race save is back: its load writes the held item's icon,
        // reports, then spawns.
        m.tick(
            tick_in(snap(Some(60_500), false), true, None),
            now + secs(4),
        );
        assert!(!m.wrong_save);
        let fx = m.tick(
            tick_in(snap(Some(60_600), true), true, items_scan(&m, &[])),
            now + secs(5),
        );
        assert_eq!(
            item_steps(&fx),
            ["icon", "report", "icon", "spawn"],
            "{fx:?}"
        );
    }

    #[test]
    fn a_grant_writes_its_icon_before_the_spawn() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "hammer"), now + ms(100));
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        let at = fx
            .iter()
            .position(|e| matches!(e, Effect::SetGoodsIcon { .. }))
            .expect("icon written");
        assert_eq!(
            fx[at..at + 2],
            [
                Effect::SetGoodsIcon {
                    goods_id: RACE_ITEM_GOODS,
                    icon_id: HAMMER_ICON,
                },
                Effect::SpawnRaceItem {
                    grant_id: 1,
                    goods_id: RACE_ITEM_GOODS,
                },
            ],
            "{fx:?}"
        );
    }

    #[test]
    fn every_held_item_shows_a_held_row() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "hammer"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(m.item_held(), None, "not before the goods are in");
        m.grant_spawn_result(1, true, now + ms(120));
        let held = m.item_held().expect("held row");
        assert_eq!(
            (held.key.as_str(), held.icon.as_str(), held.text.as_str()),
            ("hammer", "hammer", "Hammer")
        );
    }

    #[test]
    fn the_held_row_and_icon_come_back_after_a_restart() {
        // A fresh process (game restart) connects on the title screen; the
        // server names the item held.
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(holding(auth_ok_with_items("running", true), "hammer"), now);
        m.tick(tick_in(snap(Some(60_000), false), true, None), now + ms(10));
        assert_eq!(m.item_held(), None);

        // The save loads: the goods' icon is written again (the params came
        // back with the game), before the report.
        let fx = m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(item_steps(&fx), ["icon", "report"], "{fx:?}");
        assert!(fx.contains(&Effect::SetGoodsIcon {
            goods_id: RACE_ITEM_GOODS,
            icon_id: HAMMER_ICON,
        }));
        // The shell's read finds the goods: the row is the held item's.
        m.inventory_read(&["race_item".to_string()]);
        assert_eq!(m.item_held().map(|h| h.key.as_str()), Some("hammer"));
    }

    #[test]
    fn using_the_race_item_drops_the_held_row() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "hammer"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, true, now + ms(120));
        assert!(m.item_held().is_some());

        m.tick(
            tick_in(snap(Some(61_100), true), true, items_scan(&m, &[USE_FLAG])),
            now + ms(250),
        );
        assert_eq!(m.item_held(), None);
        // Nothing held any more: the next load writes no icon.
        m.tick(
            tick_in(snap(Some(61_200), false), true, None),
            now + ms(400),
        );
        let fx = m.tick(
            tick_in(snap(Some(61_300), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");
    }

    #[test]
    fn using_the_race_item_keeps_a_shield_row() {
        // A stray Race Item used while the Shield is held: the Shield's goods
        // has no use flag, its row stays.
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "shield"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, true, now + ms(120));
        m.tick(
            tick_in(snap(Some(61_100), true), true, items_scan(&m, &[USE_FLAG])),
            now + ms(250),
        );
        assert_eq!(m.item_held().map(|h| h.key.as_str()), Some("shield"));
    }

    #[test]
    fn a_self_effect_applies_without_a_banner() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            MachineMessage::ItemEffect {
                item: "mushroom".to_string(),
                effect: ItemEffectPayload::Speffect {
                    speffect_id: 1_450_826,
                    duration_ms: None,
                },
                banner: None,
                reminder: None,
            },
            now + ms(100),
        );
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(item_steps(&fx), ["apply"], "{fx:?}");
        assert!(fx.contains(&Effect::ApplySpEffect {
            speffect_id: 1_450_826,
            left_ms: None,
        }));
        assert_eq!(m.item_banner(), None);
        assert_eq!(m.item_reminders(now + ms(120)).count(), 0);
    }

    #[test]
    fn item_remove_raises_the_goods_remove_flag() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "hammer"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, true, now + ms(120));

        // A stray Shield taken back: its flag, the Hammer's row stays.
        let fx = m.handle_message(
            MachineMessage::ItemRemove {
                goods: "shield".to_string(),
                banner: None,
            },
            now + ms(200),
        );
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: SHIELD_REMOVE_FLAG,
            value: true,
        }));
        assert_eq!(m.item_held().map(|h| h.key.as_str()), Some("hammer"));

        // The Race Item taken back: the Hammer held on it goes.
        let fx = m.handle_message(
            MachineMessage::ItemRemove {
                goods: "race_item".to_string(),
                banner: None,
            },
            now + ms(300),
        );
        assert!(fx.contains(&Effect::SetGameFlag {
            flag_id: REMOVE_FLAG,
            value: true,
        }));
        assert_eq!(m.item_held(), None);
        // Nor its icon at the next load.
        m.tick(
            tick_in(snap(Some(61_200), false), true, None),
            now + ms(400),
        );
        let fx = m.tick(
            tick_in(snap(Some(61_300), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");
    }

    #[test]
    fn the_inventory_report_lists_the_goods() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.tick(
            tick_in(snap(Some(61_000), false), true, None),
            now + ms(100),
        );
        let fx = m.tick(
            tick_in(snap(Some(61_100), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        let reports: Vec<_> = fx
            .iter()
            .filter(|e| matches!(e, Effect::ReportItemInventory { .. }))
            .collect();
        assert_eq!(
            reports,
            [&Effect::ReportItemInventory {
                goods: vec![
                    ("race_item".to_string(), RACE_ITEM_GOODS),
                    ("shield".to_string(), SHIELD_GOODS),
                ],
            }]
        );
    }

    #[test]
    fn an_item_result_clears_the_held_item() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(grant(1, "hammer"), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        m.grant_spawn_result(1, true, now + ms(120));

        // The server spent the Hammer (its use capture missed here, as when
        // a resent grant raced it): the result forgets it, so the next load
        // writes no icon for it.
        m.handle_message(
            MachineMessage::ItemResult {
                item: "hammer".to_string(),
                banner: wire_banner("hammer", "Hammer"),
                reminder: None,
            },
            now + ms(200),
        );
        m.tick(
            tick_in(snap(Some(61_100), false), true, None),
            now + ms(300),
        );
        let fx = m.tick(
            tick_in(snap(Some(61_200), true), true, items_scan(&m, &[])),
            now + secs(1),
        );
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");

        // A grant after the result names the new item held.
        m.handle_message(grant(2, "red_shell"), now + secs(2));
        m.tick(
            tick_in(snap(Some(62_000), true), true, None),
            now + secs(2) + ms(10),
        );
        m.grant_spawn_result(2, true, now + secs(2) + ms(10));
        m.tick(
            tick_in(snap(Some(62_100), false), true, None),
            now + secs(3),
        );
        let fx = m.tick(
            tick_in(snap(Some(62_200), true), true, items_scan(&m, &[])),
            now + secs(4),
        );
        assert_eq!(item_steps(&fx), ["icon", "report"], "{fx:?}");
        assert!(fx.contains(&Effect::SetGoodsIcon {
            goods_id: RACE_ITEM_GOODS,
            icon_id: 60_388,
        }));
    }

    // ------------------------------------------------------------------
    // Race item effects on the play clock, across loads
    // ------------------------------------------------------------------

    const MUSHROOM_FX: u32 = 1_450_826;
    const HAMMER_FX: u32 = 1_450_827;
    const LIGHTNING_FX: u32 = 1_450_830;
    const RUNE_POUCH_FX: u32 = 1_450_821;
    /// One frame at 60 FPS, rounded up.
    const FRAME_MS: u32 = 17;
    const FRAME: Duration = Duration::from_millis(FRAME_MS as u64);

    fn timed(speffect_id: u32, duration_ms: u32) -> ItemEffectPayload {
        ItemEffectPayload::Speffect {
            speffect_id,
            duration_ms: Some(duration_ms),
        }
    }

    /// The SpEffect applications of a batch, in order: id and time left.
    fn speffects_applied(effects: &[Effect]) -> Vec<(u32, Option<u32>)> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::ApplySpEffect {
                    speffect_id,
                    left_ms,
                } => Some((*speffect_id, *left_ms)),
                _ => None,
            })
            .collect()
    }

    /// A game load: the position unreadable from `start` for `length`, the
    /// IGT held at `igt`, then the loading exit frame, whose effects it
    /// returns.
    fn load(
        m: &mut RaceMachine,
        start: Instant,
        length: Duration,
        igt: u32,
        connected: bool,
    ) -> Vec<Effect> {
        m.tick(tick_in(snap(Some(igt), false), connected, None), start);
        m.tick(
            tick_in(snap(Some(igt), false), connected, None),
            start + length / 2,
        );
        let reads = items_scan(m, &[]);
        m.tick(
            tick_in(snap(Some(igt), true), connected, reads),
            start + length,
        )
    }

    /// `left` is about `expected_ms`: the play clock stops on a load's first
    /// unreadable frame, up to a frame after the last loaded one.
    fn assert_left_about(left: Option<u32>, expected_ms: u32) {
        let left = left.expect("a timed application");
        assert!(
            (expected_ms.saturating_sub(FRAME_MS)..=expected_ms).contains(&left),
            "{left} ms left, expected about {expected_ms}"
        );
    }

    #[test]
    fn reminders_freeze_during_a_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(timed(LIGHTNING_FX, 15_000), Some(("Slowed", 15_000))),
            now + ms(100),
        );
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        // 5 s loaded, 20 s with the position unreadable, then 1 s loaded.
        m.tick(tick_in(snap(Some(66_000), true), true, None), t1 + secs(5));
        load(&mut m, t1 + secs(5), secs(20), 66_000, true);
        let t2 = t1 + secs(26);
        m.tick(tick_in(snap(Some(67_000), true), true, None), t2);
        let left: Vec<_> = m.item_reminders(t2).map(|(_, left)| left).collect();
        assert_eq!(left, [Some(secs(9))]);
    }

    #[test]
    fn effects_are_applied_again_at_the_loading_exit() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(item_hit(timed(MUSHROOM_FX, 30_000), None), now + ms(100));
        m.handle_message(
            item_hit(
                ItemEffectPayload::EquipLoad {
                    speffect_id: HAMMER_FX,
                    load_pct: 97,
                    duration_ms: Some(15_000),
                },
                Some(("Fat-roll", 15_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert_eq!(speffects_applied(&fx), [(MUSHROOM_FX, Some(30_000))]);
        assert!(fx.contains(&Effect::ApplyEquipLoad {
            speffect_id: HAMMER_FX,
            load_pct: 97,
            left_ms: Some(15_000),
        }));

        // 10 s loaded, applying nothing more, then a 20 s load from the
        // next frame.
        let fx = m.tick(tick_in(snap(Some(71_000), true), true, None), t1 + secs(10));
        assert!(item_steps(&fx).is_empty(), "{fx:?}");
        let fx = load(&mut m, t1 + secs(10) + FRAME, secs(20), 71_000, true);
        let again = speffects_applied(&fx);
        assert_eq!(
            again.iter().map(|&(id, _)| id).collect::<Vec<_>>(),
            [MUSHROOM_FX, HAMMER_FX],
            "{fx:?}"
        );
        assert_left_about(again[0].1, 20_000);
        assert_left_about(again[1].1, 5_000);
        // The Hammer's rate is still in its row: no new rate write.
        assert!(
            !fx.iter()
                .any(|e| matches!(e, Effect::ApplyEquipLoad { .. })),
            "{fx:?}"
        );

        // Once per load, not on the frames after it.
        let fx = m.tick(tick_in(snap(Some(72_000), true), true, None), t1 + secs(31));
        assert!(speffects_applied(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn an_expired_or_instant_effect_is_not_applied_again() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                ItemEffectPayload::Speffect {
                    speffect_id: RUNE_POUCH_FX,
                    duration_ms: None,
                },
                None,
            ),
            now + ms(100),
        );
        m.handle_message(item_hit(timed(LIGHTNING_FX, 15_000), None), now + ms(100));
        let t1 = now + ms(120);
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert_eq!(
            speffects_applied(&fx),
            [(RUNE_POUCH_FX, None), (LIGHTNING_FX, Some(15_000))]
        );

        // A load 5 s in: the Lightning comes back, the runes never do.
        let fx = load(&mut m, t1 + secs(5), secs(10), 62_000, true);
        assert_eq!(speffects_applied(&fx), [(LIGHTNING_FX, Some(10_000))]);
        // 11 s more of play: the Lightning is over before the next load.
        m.tick(tick_in(snap(Some(63_000), true), true, None), t1 + secs(20));
        let fx = load(&mut m, t1 + secs(26), secs(10), 64_000, true);
        assert!(speffects_applied(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn a_hit_during_a_load_refreshes_the_running_effect() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(item_hit(timed(LIGHTNING_FX, 15_000), None), now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);

        // A load 5 s in, 10 s left: a second Lightning arrives during it.
        let start = t1 + secs(5);
        m.tick(tick_in(snap(Some(62_000), false), true, None), start);
        m.handle_message(item_hit(timed(LIGHTNING_FX, 15_000), None), start + secs(2));
        let reads = items_scan(&m, &[]);
        let fx = m.tick(
            tick_in(snap(Some(62_000), true), true, reads),
            start + secs(4),
        );
        // The running one first, then the new one, whose full time wins.
        assert_eq!(
            speffects_applied(&fx),
            [(LIGHTNING_FX, Some(10_000)), (LIGHTNING_FX, Some(15_000))]
        );

        // A later load, 2 s of play on: one entry, the later end.
        let fx = load(&mut m, start + secs(6), secs(3), 63_000, true);
        assert_eq!(speffects_applied(&fx), [(LIGHTNING_FX, Some(13_000))]);
    }

    #[test]
    fn no_reapply_into_a_wrong_save() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                timed(MUSHROOM_FX, 30_000),
                Some(("Infinite stamina", 30_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(60_100), true), true, None), t1);

        // Another, further-along save is loaded: its loading exit applies
        // nothing.
        m.tick(tick_in(snap(Some(60_100), false), true, None), t1 + secs(1));
        let reads = items_scan(&m, &[]);
        let fx = m.tick(
            tick_in(snap(Some(500_000), true), true, reads),
            t1 + secs(2),
        );
        assert!(m.wrong_save);
        assert!(speffects_applied(&fx).is_empty(), "{fx:?}");
        // Played on, the wrong save stops the play clock from its next
        // frame: the reminder row does not count down there.
        let wrong = t1 + secs(2) + FRAME;
        m.tick(tick_in(snap(Some(500_017), true), true, None), wrong);
        let frozen: Vec<_> = m.item_reminders(wrong).map(|(_, left)| left).collect();
        m.tick(tick_in(snap(Some(501_000), true), true, None), t1 + secs(3));
        let later: Vec<_> = m
            .item_reminders(t1 + secs(3))
            .map(|(_, left)| left)
            .collect();
        assert_eq!(later, frozen);

        // The race save is back: its loading exit applies the Mushroom
        // again, the time on the wrong save not counted (a frame at most).
        m.tick(tick_in(snap(Some(60_500), false), true, None), t1 + secs(4));
        assert!(!m.wrong_save);
        let reads = items_scan(&m, &[]);
        let fx = m.tick(tick_in(snap(Some(60_600), true), true, reads), t1 + secs(5));
        let again = speffects_applied(&fx);
        assert_eq!(again.len(), 1, "{fx:?}");
        assert_eq!(again[0].0, MUSHROOM_FX);
        assert_left_about(again[0].1, 29_000);
    }

    #[test]
    fn effects_come_back_after_a_load_while_disconnected() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(item_hit(timed(MUSHROOM_FX, 30_000), None), now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            t1 + secs(1),
        );

        // The effects are local: no connection needed.
        let fx = load(&mut m, t1 + secs(2), secs(5), 62_000, false);
        assert_eq!(speffects_applied(&fx), [(MUSHROOM_FX, Some(28_000))]);

        // The reconnect frame is no load: the game kept the effect.
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t1 + secs(8),
        );
        let reads = items_scan(&m, &[]);
        let fx = m.tick(tick_in(snap(Some(63_000), true), true, reads), t1 + secs(9));
        assert!(item_steps(&fx).contains(&"ready"), "{fx:?}");
        assert!(speffects_applied(&fx).is_empty(), "{fx:?}");
    }

    #[test]
    fn effects_go_with_the_run() {
        for end in ["new start", "finished", "abandoned", "another participant"] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            m.handle_message(item_hit(timed(MUSHROOM_FX, 30_000), None), now + ms(100));
            let t1 = now + ms(120);
            let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
            assert_eq!(
                speffects_applied(&fx),
                [(MUSHROOM_FX, Some(30_000))],
                "{end}"
            );
            let t2 = t1 + secs(1);
            match end {
                "new start" => {
                    // A race reset: the same runner authenticates again, the
                    // race in setup, and the start comes before any frame.
                    m.handle_message(auth_ok_with_items("setup", true), t2);
                    m.handle_message(MachineMessage::RaceStart(0), t2 + ms(10));
                }
                "another participant" => {
                    let mut other = auth_ok_with_items("running", true);
                    if let MachineMessage::AuthOk {
                        participant_id,
                        participants,
                        ..
                    } = &mut other
                    {
                        *participant_id = "p2".to_string();
                        participants[0] = test_participant("p2", "playing", 1);
                    }
                    m.handle_message(other, t2);
                }
                status => {
                    m.handle_message(
                        MachineMessage::LeaderboardUpdate {
                            participants: vec![test_participant("p1", status, 3)],
                            leader_splits: None,
                        },
                        t2,
                    );
                    m.tick(tick_in(snap(Some(61_500), true), true, None), t2 + ms(10));
                    // Even a run live again later (its status put back)
                    // gets nothing back.
                    m.handle_message(
                        MachineMessage::LeaderboardUpdate {
                            participants: vec![test_participant("p1", "playing", 3)],
                            leader_splits: None,
                        },
                        t2 + ms(20),
                    );
                }
            }
            let fx = load(&mut m, t1 + secs(2), secs(5), 62_000, true);
            assert!(speffects_applied(&fx).is_empty(), "{end}: {fx:?}");
        }
    }

    // ------------------------------------------------------------------
    // Memory effects
    // ------------------------------------------------------------------

    /// The memory states a batch writes, with their foes walk.
    fn memory_writes(effects: &[Effect]) -> Vec<(MemoryState, bool)> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::ApplyMemoryState { state, walk_foes } => Some((*state, *walk_foes)),
                _ => None,
            })
            .collect()
    }

    /// Loaded frames at `igt`, one every `FRAME` after `from` up to `until`:
    /// the memory writes, with when each went.
    fn memory_frames(
        m: &mut RaceMachine,
        igt: u32,
        from: Instant,
        until: Instant,
    ) -> Vec<(Instant, MemoryState, bool)> {
        let mut writes = Vec::new();
        let mut at = from + FRAME;
        while at <= until {
            let fx = m.tick(tick_in(snap(Some(igt), true), true, None), at);
            writes.extend(
                memory_writes(&fx)
                    .into_iter()
                    .map(|(state, walk)| (at, state, walk)),
            );
            at += FRAME;
        }
        writes
    }

    /// `at` falls in the frame starting at `from`.
    fn assert_within_a_frame(at: Instant, from: Instant) {
        assert!(
            (from..from + FRAME).contains(&at),
            "{:?} after the expected time",
            at.checked_duration_since(from)
        );
    }

    #[test]
    fn a_memory_effect_is_written_on_change_and_refreshed() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                ItemEffectPayload::SlowMo {
                    speed_pct: 50,
                    duration_ms: 15_000,
                },
                Some(("Slow-mo", 15_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        let slow = MemoryState {
            anim_speed: Some(0.5),
            ..MemoryState::default()
        };
        // Written when applied, with its banner and reminder as any effect.
        assert_eq!(memory_writes(&fx), [(slow, false)]);
        assert_eq!(m.item_reminders(t1).count(), 1);
        assert!(banner_title(&m).is_some());

        // Written again every 250 ms of wall time, not every frame; no foes
        // to walk.
        let writes = memory_frames(&mut m, 61_000, t1, t1 + secs(2));
        assert_eq!(writes.len(), 7, "{writes:?}");
        let mut last = t1;
        for &(at, state, walk) in &writes {
            assert_eq!((state, walk), (slow, false));
            assert_within_a_frame(at, last + ms(250));
            last = at;
        }

        // Unseen Foes on top: written at once with a walk, then every
        // second's write walks the foes again, the others leave them.
        let t2 = t1 + secs(2);
        m.handle_message(
            item_hit(
                ItemEffectPayload::UnseenFoes {
                    duration_ms: 15_000,
                },
                None,
            ),
            t2,
        );
        let both = MemoryState {
            foes_hidden: true,
            ..slow
        };
        let writes = memory_frames(&mut m, 61_000, t2, t2 + secs(5));
        assert_eq!(writes[0], (t2 + FRAME, both, true));
        assert!(writes.iter().all(|&(_, state, _)| state == both));
        let walks: Vec<Instant> = writes
            .iter()
            .filter(|&&(_, _, walk)| walk)
            .map(|&(at, _, _)| at)
            .collect();
        assert_eq!(walks.len(), 5, "{writes:?}");
        for pair in walks.windows(2) {
            assert_within_a_frame(pair[1], pair[0] + secs(1));
        }
        assert!(writes.len() > 3 * walks.len(), "{writes:?}");

        // The Slow-mo ends (15 s from t1): the speed goes back, the foes stay
        // hidden. The Unseen Foes ends (15 s from its first frame): one write
        // of the defaults, walking the foes back, then nothing.
        let writes = memory_frames(&mut m, 61_000, t2 + secs(5), t2 + secs(20));
        let foes_only = MemoryState {
            foes_hidden: true,
            ..MemoryState::default()
        };
        let first_foes_only = writes.iter().position(|w| w.1 == foes_only).unwrap();
        assert_within_a_frame(writes[first_foes_only].0, t1 + secs(15));
        assert!(writes[..first_foes_only].iter().all(|w| w.1 == both));
        let (end_at, end_state, end_walk) = *writes.last().unwrap();
        assert_eq!((end_state, end_walk), (MemoryState::default(), true));
        assert_within_a_frame(end_at, t2 + FRAME + secs(15));
        assert!(writes[first_foes_only..writes.len() - 1]
            .iter()
            .all(|w| w.1 == foes_only));
    }

    #[test]
    fn memory_effects_come_back_at_the_loading_exit() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                ItemEffectPayload::Vanish {
                    duration_ms: 15_000,
                },
                Some(("Invisible", 15_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        let hidden = MemoryState {
            player_hidden: true,
            ..MemoryState::default()
        };
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert_eq!(memory_writes(&fx), [(hidden, false)]);

        // 5 s loaded, then a 20 s load from the next frame: nothing is
        // written while the player is not loaded.
        memory_frames(&mut m, 61_000, t1, t1 + secs(5));
        let start = t1 + secs(5) + FRAME;
        let mut fx = m.tick(tick_in(snap(Some(66_000), false), true, None), start);
        fx.extend(m.tick(
            tick_in(snap(Some(66_000), false), true, None),
            start + secs(10),
        ));
        assert!(memory_writes(&fx).is_empty(), "{fx:?}");

        // The loading exit writes it again, with no change to trigger it.
        let exit = start + secs(20);
        let reads = items_scan(&m, &[]);
        let fx = m.tick(tick_in(snap(Some(66_000), true), true, reads), exit);
        assert_eq!(memory_writes(&fx), [(hidden, false)]);

        // Its time left runs from there, the load not counted: 5 s and a
        // frame were played before it.
        let writes = memory_frames(&mut m, 66_000, exit, exit + secs(12));
        let (end_at, end_state, _) = *writes.last().unwrap();
        assert_eq!(end_state, MemoryState::default());
        assert_within_a_frame(end_at, exit + secs(10) - FRAME);
        assert!(writes[..writes.len() - 1].iter().all(|w| w.1 == hidden));
    }

    #[test]
    fn a_new_start_forgets_the_unacked_uses_of_the_voided_run() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // A use sent, never acked (its resolution failed on the server),
        // beside a fog flag in flight.
        let scan = items_scan(&m, &[USE_FLAG]);
        m.tick(tick_in(snap(Some(60_000), true), true, scan), now + ms(150));
        m.in_flight_event_flags.insert(
            9_999,
            BufferedEventFlag {
                flag_id: 100,
                igt_ms: 59_000,
            },
        );
        let in_flight = |m: &RaceMachine| -> Vec<u32> {
            let mut flags: Vec<_> = m
                .in_flight_event_flags
                .values()
                .map(|f| f.flag_id)
                .collect();
            flags.sort_unstable();
            flags
        };
        assert_eq!(in_flight(&m), [100, USE_FLAG]);

        // A race reset run again: the use belonged to the voided run.
        m.handle_message(auth_ok_with_items("setup", true), now + secs(1));
        m.handle_message(MachineMessage::RaceStart(0), now + secs(2));
        assert_eq!(in_flight(&m), [100]);
    }

    #[test]
    fn a_memory_effects_row_goes_with_the_run_a_timed_one_stays() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                ItemEffectPayload::Scale {
                    scale_pct: 150,
                    duration_ms: 15_000,
                },
                Some(("Giant", 15_000)),
            ),
            now + ms(100),
        );
        m.handle_message(
            item_hit(
                ItemEffectPayload::Speffect {
                    speffect_id: 1_450_827,
                    duration_ms: Some(15_000),
                },
                Some(("Flasks blocked", 15_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        let rows = |m: &RaceMachine, at| -> Vec<String> {
            m.item_reminders(at)
                .map(|(row, _)| row.text.clone())
                .collect()
        };
        assert_eq!(rows(&m, t1), ["Giant", "Flasks blocked"]);

        // The finish writes the scale back at once, so its row goes; the
        // game still runs the SpEffect out, under its row.
        let t2 = t1 + secs(1);
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![test_participant("p1", "finished", 3)],
                leader_splits: None,
            },
            t2,
        );
        m.tick(tick_in(snap(Some(62_000), true), true, None), t2 + ms(10));
        assert_eq!(rows(&m, t2 + ms(10)), ["Flasks blocked"]);
    }

    #[test]
    fn memory_effects_are_restored_when_the_run_ends() {
        let first_person = MemoryState {
            player_hidden: true,
            foes_hidden: true,
            camera: Some(CameraVariant::FirstPerson),
            ..MemoryState::default()
        };
        for end in ["new start", "finished", "another participant"] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            m.handle_message(
                item_hit(
                    ItemEffectPayload::Camera {
                        variant: CameraVariant::FirstPerson,
                        duration_ms: 15_000,
                    },
                    None,
                ),
                now + ms(100),
            );
            m.handle_message(
                item_hit(
                    ItemEffectPayload::UnseenFoes {
                        duration_ms: 15_000,
                    },
                    None,
                ),
                now + ms(100),
            );
            let t1 = now + ms(120);
            let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
            assert_eq!(memory_writes(&fx), [(first_person, true)], "{end}");

            let t2 = t1 + secs(1);
            let mut fx = Vec::new();
            match end {
                "new start" => {
                    // A race reset: the same runner authenticates again, the
                    // race in setup, and the start comes before any frame.
                    fx.extend(m.handle_message(auth_ok_with_items("setup", true), t2));
                    fx.extend(m.handle_message(MachineMessage::RaceStart(0), t2 + ms(10)));
                }
                "another participant" => {
                    let mut other = auth_ok_with_items("running", true);
                    if let MachineMessage::AuthOk {
                        participant_id,
                        participants,
                        ..
                    } = &mut other
                    {
                        *participant_id = "p2".to_string();
                        participants[0] = test_participant("p2", "playing", 1);
                    }
                    fx.extend(m.handle_message(other, t2));
                }
                status => {
                    fx.extend(m.handle_message(
                        MachineMessage::LeaderboardUpdate {
                            participants: vec![test_participant("p1", status, 3)],
                            leader_splits: None,
                        },
                        t2,
                    ));
                    fx.extend(m.tick(tick_in(snap(Some(61_500), true), true, None), t2 + ms(10)));
                    // Even a run live again later (its status put back)
                    // gets nothing back.
                    fx.extend(m.handle_message(
                        MachineMessage::LeaderboardUpdate {
                            participants: vec![test_participant("p1", "playing", 3)],
                            leader_splits: None,
                        },
                        t2 + ms(20),
                    ));
                }
            }
            // The next frames, a load, and past the effects' end: the
            // defaults once, the foes walked back, then nothing.
            let mut writes = memory_writes(&fx);
            writes.extend(
                memory_frames(&mut m, 61_500, t2 + ms(20), t2 + secs(2))
                    .into_iter()
                    .map(|(_, state, walk)| (state, walk)),
            );
            writes.extend(memory_writes(&load(
                &mut m,
                t2 + secs(3),
                secs(5),
                62_000,
                true,
            )));
            writes.extend(
                memory_frames(&mut m, 62_000, t2 + secs(8), t2 + secs(20))
                    .into_iter()
                    .map(|(_, state, walk)| (state, walk)),
            );
            assert_eq!(writes, [(MemoryState::default(), true)], "{end}");
        }
    }

    #[test]
    fn a_wrong_save_gets_the_defaults_and_the_race_save_the_effects() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            item_hit(
                ItemEffectPayload::Scale {
                    scale_pct: 50,
                    duration_ms: 15_000,
                },
                Some(("Shrunk", 15_000)),
            ),
            now + ms(100),
        );
        m.handle_message(
            item_hit(
                ItemEffectPayload::UnseenFoes {
                    duration_ms: 15_000,
                },
                None,
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        let shrunk = MemoryState {
            foes_hidden: true,
            scale: Some(0.5),
            ..MemoryState::default()
        };
        let fx = m.tick(tick_in(snap(Some(60_100), true), true, None), t1);
        assert_eq!(memory_writes(&fx), [(shrunk, true)]);

        // Another, further-along save is loaded: its loading exit gets the
        // defaults once, the foes walked back.
        m.tick(tick_in(snap(Some(60_100), false), true, None), t1 + secs(1));
        let reads = items_scan(&m, &[]);
        let fx = m.tick(
            tick_in(snap(Some(500_000), true), true, reads),
            t1 + secs(2),
        );
        assert!(m.wrong_save);
        assert_eq!(memory_writes(&fx), [(MemoryState::default(), true)]);
        // Played on, it gets no refresh.
        let writes = memory_frames(&mut m, 500_000, t1 + secs(2), t1 + secs(4));
        assert!(writes.is_empty(), "{writes:?}");

        // The race save is back: its loading exit writes the effects again,
        // with the time they had left (1 s and a frame were played).
        m.tick(tick_in(snap(Some(60_500), false), true, None), t1 + secs(4));
        assert!(!m.wrong_save);
        let reads = items_scan(&m, &[]);
        let exit = t1 + secs(5);
        let fx = m.tick(tick_in(snap(Some(60_600), true), true, reads), exit);
        assert_eq!(memory_writes(&fx), [(shrunk, true)]);
        let writes = memory_frames(&mut m, 60_600, exit, exit + secs(15));
        let (end_at, end_state, end_walk) = *writes.last().unwrap();
        assert_eq!((end_state, end_walk), (MemoryState::default(), true));
        assert_within_a_frame(end_at, exit + secs(14) - FRAME);
    }

    fn lightning_hit() -> MachineMessage {
        item_hit(
            ItemEffectPayload::Lightning {
                speffect_id: LIGHTNING_FX,
                scale_pct: 50,
                duration_ms: 15_000,
            },
            Some(("Slowed and shrunk", 15_000)),
        )
    }

    fn giant_hit() -> MachineMessage {
        item_hit(
            ItemEffectPayload::Scale {
                scale_pct: 150,
                duration_ms: 15_000,
            },
            Some(("Giant", 15_000)),
        )
    }

    fn reminder_rows(m: &RaceMachine, at: Instant) -> Vec<String> {
        m.item_reminders(at)
            .map(|(row, _)| row.text.clone())
            .collect()
    }

    fn scales(writes: &[(MemoryState, bool)]) -> Vec<Option<f32>> {
        writes.iter().map(|(state, _)| state.scale).collect()
    }

    #[test]
    fn the_lightning_slows_and_shrinks() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(lightning_hit(), now + ms(100));
        let t1 = now + ms(120);
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert!(
            fx.contains(&Effect::ApplySpEffect {
                speffect_id: LIGHTNING_FX,
                left_ms: Some(15_000),
            }),
            "{fx:?}"
        );
        assert_eq!(scales(&memory_writes(&fx)), [Some(0.5)]);
        assert_eq!(reminder_rows(&m, t1), ["Slowed and shrunk"]);
        // Both end with its 15 s of play.
        let writes = memory_frames(&mut m, 61_000, t1, t1 + secs(16));
        let (end_at, end_state, _) = *writes.last().unwrap();
        assert_eq!(end_state.scale, None);
        assert_within_a_frame(end_at, t1 + secs(15));
        assert!(reminder_rows(&m, t1 + secs(16)).is_empty());
    }

    #[test]
    fn the_lightning_survives_a_load() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(lightning_hit(), now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        memory_frames(&mut m, 61_000, t1, t1 + secs(5));
        // A 5 s load from 5 s in: both come back with about 10 s left.
        let fx = load(&mut m, t1 + secs(5), secs(5), 61_000, true);
        let left = fx.iter().find_map(|e| match e {
            Effect::ApplySpEffect {
                speffect_id: LIGHTNING_FX,
                left_ms,
            } => Some(*left_ms),
            _ => None,
        });
        assert_left_about(left.flatten(), 10_000);
        assert_eq!(scales(&memory_writes(&fx)), [Some(0.5)]);
        let exit = t1 + secs(10);
        let writes = memory_frames(&mut m, 61_000, exit, exit + secs(11));
        let (end_at, end_state, _) = *writes.last().unwrap();
        assert_eq!(end_state.scale, None);
        assert!(
            (exit + secs(9)..exit + secs(10) + FRAME).contains(&end_at),
            "ended {:?} after the exit",
            end_at - exit
        );
    }

    #[test]
    fn a_giant_during_the_lightning_keeps_its_row() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(lightning_hit(), now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        // The Giant 5 s later: his size wins, the Lightning's row stays (its
        // slow walk goes on) and goes at its own end.
        let t2 = t1 + secs(5);
        m.handle_message(giant_hit(), t2);
        let fx = m.tick(tick_in(snap(Some(66_000), true), true, None), t2);
        assert_eq!(scales(&memory_writes(&fx)), [Some(1.5)]);
        assert_eq!(reminder_rows(&m, t2), ["Slowed and shrunk", "Giant"]);
        assert_eq!(reminder_rows(&m, t1 + secs(16)), ["Giant"]);
    }

    #[test]
    fn the_lightning_replaces_a_giant() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(giant_hit(), now + ms(100));
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        let t2 = t1 + secs(5);
        m.handle_message(lightning_hit(), t2);
        let fx = m.tick(tick_in(snap(Some(66_000), true), true, None), t2);
        assert_eq!(scales(&memory_writes(&fx)), [Some(0.5)]);
        assert_eq!(reminder_rows(&m, t2), ["Slowed and shrunk"]);
    }

    #[test]
    fn a_second_hit_of_a_memory_kind_replaces_its_reminder_row() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let reminders = |m: &RaceMachine, at| -> Vec<String> {
            m.item_reminders(at)
                .map(|(row, _)| row.text.clone())
                .collect()
        };
        // A shrink, then a Giant 5 s later: one scale, one row, the Giant's.
        m.handle_message(
            item_hit(
                ItemEffectPayload::Scale {
                    scale_pct: 50,
                    duration_ms: 15_000,
                },
                Some(("Shrunk", 15_000)),
            ),
            now + ms(100),
        );
        let t1 = now + ms(120);
        m.tick(tick_in(snap(Some(61_000), true), true, None), t1);
        assert_eq!(reminders(&m, t1), ["Shrunk"]);
        let t2 = t1 + secs(5);
        m.handle_message(
            item_hit(
                ItemEffectPayload::Scale {
                    scale_pct: 150,
                    duration_ms: 15_000,
                },
                Some(("Giant", 15_000)),
            ),
            t2,
        );
        m.tick(tick_in(snap(Some(66_000), true), true, None), t2);
        assert_eq!(reminders(&m, t2), ["Giant"]);
        // A Vanish beside it keeps its own row; a Camera then another
        // variant: the later one's row alone.
        m.handle_message(
            item_hit(
                ItemEffectPayload::Vanish {
                    duration_ms: 15_000,
                },
                Some(("Invisible", 15_000)),
            ),
            t2 + ms(10),
        );
        for (variant, text) in [
            (CameraVariant::Inverted, "Upside down"),
            (CameraVariant::Wide, "Wide camera"),
        ] {
            m.handle_message(
                item_hit(
                    ItemEffectPayload::Camera {
                        variant,
                        duration_ms: 15_000,
                    },
                    Some((text, 15_000)),
                ),
                t2 + ms(10),
            );
        }
        let t3 = t2 + ms(20);
        m.tick(tick_in(snap(Some(66_020), true), true, None), t3);
        assert_eq!(reminders(&m, t3), ["Giant", "Invisible", "Wide camera"]);
    }

    #[test]
    fn an_unknown_camera_variant_is_dropped_with_a_warning() {
        let logs = LogCapture::default();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(logs.clone())
            .with_max_level(tracing::Level::WARN)
            .with_ansi(false)
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            let mut fx = m.handle_message(
                item_hit(
                    ItemEffectPayload::Camera {
                        variant: CameraVariant::Unknown,
                        duration_ms: 15_000,
                    },
                    Some(("Camera", 15_000)),
                ),
                now + ms(100),
            );
            fx.extend(m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120)));
            assert!(memory_writes(&fx).is_empty(), "{fx:?}");
            // Dropped whole: no banner, no reminder.
            assert_eq!(banner_title(&m), None);
            assert_eq!(m.item_reminders(now + ms(120)).count(), 0);
        });
        assert!(
            logs.contents()
                .contains("[ITEMS] Effect of an unknown kind or variant, dropped"),
            "{}",
            logs.contents()
        );
    }

    #[test]
    fn an_item_notice_shows_its_banner() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        // A notice applies nothing: it waits for no load.
        m.tick(
            tick_in(snap(Some(60_000), false), true, None),
            now + ms(100),
        );
        let mut fx = m.handle_message(
            MachineMessage::ItemNotice {
                banner: wire_banner("star", "Star"),
            },
            now + ms(200),
        );
        // In the tone of the Shield's block banner.
        assert_eq!(banner_title(&m), Some(("STAR".to_string(), FeedTone::Gain)));
        fx.extend(m.tick(
            tick_in(snap(Some(60_100), true), true, items_scan(&m, &[])),
            now + secs(1),
        ));
        assert_eq!(item_steps(&fx), ["report"], "{fx:?}");
        assert!(memory_writes(&fx).is_empty(), "{fx:?}");
        assert_eq!(m.item_reminders(now + secs(1)).count(), 0);
    }

    // ------------------------------------------------------------------
    // Talisman Thief, Junk Weapon, Hunter
    // ------------------------------------------------------------------

    /// The Hunter's NpcParam row (tier 6) and think row.
    const HUNTER_ROW: u32 = 1_450_855;
    const HUNTER_THINK: u32 = 1_450_850;

    fn lot_4_hit(
        item: &str,
        effect: ItemEffectPayload,
        banner: Option<&str>,
        reminder: Option<&str>,
    ) -> MachineMessage {
        MachineMessage::ItemEffect {
            item: item.to_string(),
            effect,
            banner: banner.map(|title| wire_banner(item, title)),
            reminder: reminder.map(|text| ItemReminder {
                text: text.to_string(),
                duration_ms: 60_000,
            }),
        }
    }

    fn steal(report_id: u64) -> MachineMessage {
        lot_4_hit(
            "talisman_thief",
            ItemEffectPayload::StealTalisman {
                talismans: vec![TalismanFlag {
                    id: 1000,
                    flag: 1_050_290_300,
                }],
                roll: 5,
                report_id,
            },
            None,
            None,
        )
    }

    fn hunter(report_id: u64) -> MachineMessage {
        lot_4_hit(
            "hunter",
            ItemEffectPayload::Hunter {
                chr_id: 2130,
                npc_param_id: HUNTER_ROW,
                think_id: HUNTER_THINK,
                duration_ms: 60_000,
                report_id,
            },
            Some("Hunter"),
            Some("Hunted"),
        )
    }

    /// The Hunter's effects and the item reports of a batch.
    fn hunter_steps(effects: Vec<Effect>) -> Vec<Effect> {
        effects
            .into_iter()
            .filter(|e| {
                matches!(
                    e,
                    Effect::RequestHunter { .. }
                        | Effect::FindHunter { .. }
                        | Effect::EndHunter { .. }
                        | Effect::SendItemReport { .. }
                )
            })
            .collect()
    }

    /// Loaded frames at `igt`, one every `FRAME` after `from` up to `until`,
    /// every Hunter spawn handed to the game and every look finding him
    /// while `found` says so: the Hunter's effects and the reports, with
    /// when.
    fn hunter_frames(
        m: &mut RaceMachine,
        from: Instant,
        until: Instant,
        found: impl Fn(Instant) -> bool,
    ) -> Vec<(Instant, Effect)> {
        let mut steps = Vec::new();
        let mut at = from + FRAME;
        while at <= until {
            for effect in m.tick(tick_in(snap(Some(61_000), true), true, None), at) {
                match effect {
                    Effect::RequestHunter { .. } => m.hunter_request_result(true, at),
                    Effect::FindHunter { .. } => m.hunter_seen(found(at), at),
                    Effect::EndHunter { .. } | Effect::SendItemReport { .. } => {}
                    _ => continue,
                }
                steps.push((at, effect));
            }
            at += FRAME;
        }
        steps
    }

    fn reminder_texts(m: &RaceMachine, now: Instant) -> Vec<String> {
        m.item_reminders(now)
            .map(|(row, _)| row.text.clone())
            .collect()
    }

    #[test]
    fn a_steal_reports_what_the_shell_took() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(steal(7), now + ms(100));
        // Applied on a loaded frame, as any effect.
        let fx = m.tick(
            tick_in(snap(Some(61_000), false), true, None),
            now + ms(120),
        );
        assert!(
            !fx.iter().any(|e| matches!(e, Effect::StealTalisman { .. })),
            "{fx:?}"
        );
        let fx = load(&mut m, now + ms(140), secs(5), 61_000, true);
        assert!(
            fx.contains(&Effect::StealTalisman {
                talismans: vec![TalismanFlag {
                    id: 1000,
                    flag: 1_050_290_300
                }],
                roll: 5,
                report_id: 7,
            }),
            "{fx:?}"
        );
        assert_eq!(
            m.talisman_steal_result(7, Some(1000)),
            [Effect::SendItemReport {
                report_id: 7,
                landed: true,
                talisman_id: Some(1000),
            }]
        );
        // No banner of its own: the server sends one after the report.
        assert_eq!(banner_title(&m), None);
    }

    #[test]
    fn a_failed_steal_reports_nothing_taken() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(steal(8), now + ms(100));
        m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        assert_eq!(
            m.talisman_steal_result(8, None),
            [Effect::SendItemReport {
                report_id: 8,
                landed: false,
                talisman_id: None,
            }]
        );
    }

    #[test]
    fn the_gift_and_the_junk_weapon_are_applied_with_their_banner() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(
            lot_4_hit(
                "talisman_thief",
                ItemEffectPayload::Talisman { talisman_id: 1000 },
                Some("Talisman Thief"),
                None,
            ),
            now + ms(100),
        );
        m.handle_message(
            lot_4_hit(
                "junk_weapon",
                ItemEffectPayload::JunkWeapon {
                    weapon_id: 11_010_000,
                },
                Some("Junk Weapon"),
                None,
            ),
            now + ms(100),
        );
        let fx = m.tick(tick_in(snap(Some(61_000), true), true, None), now + ms(120));
        let applied: Vec<_> = fx
            .iter()
            .filter(|e| {
                matches!(
                    e,
                    Effect::SpawnTalisman { .. } | Effect::EquipJunkWeapon { .. }
                )
            })
            .collect();
        assert_eq!(
            applied,
            [
                &Effect::SpawnTalisman { talisman_id: 1000 },
                &Effect::EquipJunkWeapon {
                    weapon_id: 11_010_000
                }
            ]
        );
        assert_eq!(
            banner_title(&m),
            Some(("TALISMAN THIEF".to_string(), FeedTone::Malus))
        );
    }

    #[test]
    fn the_hunter_banner_waits_for_him() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), now + ms(100));
        // Not seen for 1 s.
        let t1 = now + ms(100);
        let steps = hunter_frames(&mut m, t1, t1 + secs(1), |_| false);
        assert_eq!(
            steps[0],
            (
                t1 + FRAME,
                Effect::RequestHunter {
                    chr_id: 2130,
                    npc_param_id: HUNTER_ROW,
                    think_id: HUNTER_THINK,
                }
            )
        );
        assert!(steps[1..].iter().all(|(_, e)| *e
            == Effect::FindHunter {
                npc_param_id: HUNTER_ROW
            }));
        assert_eq!(steps.len(), 4, "{steps:?}");
        assert_eq!(banner_title(&m), None);
        assert!(reminder_texts(&m, t1 + secs(1)).is_empty());

        // Seen: his banner and reminder show, and he is reported landed.
        let t2 = t1 + secs(1);
        let steps = hunter_frames(&mut m, t2, t2 + secs(1), |_| true);
        let report = Effect::SendItemReport {
            report_id: 13,
            landed: true,
            talisman_id: None,
        };
        assert_eq!(
            steps.iter().filter(|(_, e)| *e == report).count(),
            1,
            "{steps:?}"
        );
        assert_eq!(
            banner_title(&m),
            Some(("HUNTER".to_string(), FeedTone::Malus))
        );
        assert_eq!(reminder_texts(&m, t2 + secs(1)), ["Hunted"]);
    }

    #[test]
    fn a_hunter_arriving_after_the_last_miss_is_ended_unseen() {
        let now = Instant::now();
        let t1 = now + ms(100);
        // When the last miss is reported, never seeing him.
        let missed = Effect::SendItemReport {
            report_id: 13,
            landed: false,
            talisman_id: None,
        };
        let mut dry = running_items_machine(now);
        dry.handle_message(hunter(13), t1);
        let last = hunter_frames(&mut dry, t1, t1 + secs(30), |_| false)
            .into_iter()
            .find(|(_, e)| *e == missed)
            .unwrap()
            .0;

        // He shows up 4 s after it: ended once, with no banner (one shown
        // then would still be up 2 s later), no row and no other report.
        let late = |at: Instant| at >= last + secs(4);
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), t1);
        let steps = hunter_frames(&mut m, t1, last + secs(6), late);
        let after: Vec<_> = steps.into_iter().filter(|(at, _)| *at > last).collect();
        let ends: Vec<_> = after
            .iter()
            .filter(|(_, e)| matches!(e, Effect::EndHunter { .. }))
            .collect();
        assert_eq!(ends.len(), 1, "{after:?}");
        assert_eq!(after.last(), Some(ends[0]), "{after:?}");
        assert!(
            !after
                .iter()
                .any(|(_, e)| matches!(e, Effect::SendItemReport { .. })),
            "{after:?}"
        );
        assert_eq!(banner_title(&m), None);
        assert!(reminder_texts(&m, last + secs(6)).is_empty());
        // Nothing more for him.
        assert_eq!(
            hunter_frames(&mut m, last + secs(6), last + secs(30), late),
            []
        );
    }

    #[test]
    fn the_hunter_waits_for_the_load_to_settle() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), now + ms(100));
        // Received during a load: applied at its exit, spawned 2.5 s later.
        let fx = load(&mut m, now + ms(100), secs(5), 61_000, true);
        assert_eq!(hunter_steps(fx), []);
        let exit = now + ms(100) + secs(5);
        let steps = hunter_frames(&mut m, exit, exit + secs(3), |_| false);
        assert!(
            matches!(steps[0].1, Effect::RequestHunter { .. }),
            "{steps:?}"
        );
        assert!(
            (exit + secs(5) / 2..exit + secs(5) / 2 + FRAME).contains(&steps[0].0),
            "{:?} after the exit",
            steps[0].0 - exit
        );
    }

    #[test]
    fn a_second_hunter_is_reported_missed_at_once() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), now + ms(100));
        let t1 = now + ms(100);
        hunter_frames(&mut m, t1, t1 + ms(500), |_| false);
        m.handle_message(hunter(14), t1 + ms(500));
        let steps = hunter_frames(&mut m, t1 + ms(500), t1 + secs(2), |_| true);
        assert_eq!(
            steps[0],
            (
                t1 + ms(500) + FRAME,
                Effect::SendItemReport {
                    report_id: 14,
                    landed: false,
                    talisman_id: None,
                }
            )
        );
        // The first one goes on: found, reported landed, his banner alone.
        assert!(steps.iter().any(|(_, e)| *e
            == Effect::SendItemReport {
                report_id: 13,
                landed: true,
                talisman_id: None,
            }));
        assert!(!steps
            .iter()
            .any(|(_, e)| matches!(e, Effect::RequestHunter { .. })));
        assert_eq!(reminder_texts(&m, t1 + secs(2)), ["Hunted"]);
    }

    #[test]
    fn the_hunted_row_ends_with_the_hunt() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), now + ms(100));
        let t1 = now + ms(100);
        hunter_frames(&mut m, t1, t1 + secs(2), |_| true);
        assert_eq!(reminder_texts(&m, t1 + secs(2)), ["Hunted"]);

        // A load or a kill removed him: the next look ends the hunt, his row
        // with it (well before its 60 s), and nothing more comes out for
        // him, no end either.
        let gone = t1 + secs(2);
        let mut steps = hunter_frames(&mut m, gone, gone + secs(2), |_| false);
        assert_eq!(steps.len(), 1, "{steps:?}");
        assert!(reminder_texts(&m, gone + secs(2)).is_empty());
        steps.extend(hunter_frames(
            &mut m,
            gone + secs(2),
            gone + secs(70),
            |_| false,
        ));
        assert_eq!(
            steps,
            [(
                steps[0].0,
                Effect::FindHunter {
                    npc_param_id: HUNTER_ROW
                }
            )]
        );
    }

    /// A quit-out from `start`: the menu and the save load last `length`,
    /// then the save is back in the world with the IGT it last flushed
    /// (1.5 s behind the 61 s the Hunter frames run at): the loading exit's
    /// effects.
    fn quit_out_load(m: &mut RaceMachine, start: Instant, length: Duration) -> Vec<Effect> {
        m.tick(tick_in(snap(None, false), true, None), start);
        m.tick(tick_in(snap(None, false), true, None), start + length / 2);
        let reads = items_scan(m, &[]);
        m.tick(
            tick_in(snap(Some(59_500), true), true, reads),
            start + length,
        )
    }

    #[test]
    fn a_quit_out_does_not_shake_off_the_hunter() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let t1 = now + ms(100);
        m.handle_message(hunter(13), t1);
        let before = hunter_frames(&mut m, t1, t1 + secs(5), |_| true);
        let landed = Effect::SendItemReport {
            report_id: 13,
            landed: true,
            talisman_id: None,
        };
        assert_eq!(
            before.iter().filter(|(_, e)| *e == landed).count(),
            1,
            "{before:?}"
        );

        // Quit out 5 s in: the exit keeps the hunt and its row.
        let quit = t1 + secs(5);
        let exit = quit + secs(20);
        let fx = quit_out_load(&mut m, quit, secs(20));
        assert!(m
            .get_status(exit)
            .is_some_and(|s| s.starts_with("Quit-out")));
        assert_eq!(hunter_steps(fx), []);
        assert_eq!(reminder_texts(&m, exit), ["Hunted"]);

        // Brought back once the player settled, with no new report; ended
        // when his 60 s of play end (5 s were played before the quit-out).
        let mut after = hunter_frames(&mut m, exit, exit + secs(30), |_| true);
        assert_eq!(reminder_texts(&m, exit + secs(30)), ["Hunted"]);
        after.extend(hunter_frames(
            &mut m,
            exit + secs(30),
            exit + secs(70),
            |_| true,
        ));
        assert!(
            matches!(after[0].1, Effect::RequestHunter { .. }),
            "{after:?}"
        );
        assert!(
            (exit + secs(5) / 2..exit + secs(5) / 2 + FRAME).contains(&after[0].0),
            "{:?} after the exit",
            after[0].0 - exit
        );
        assert!(
            !after
                .iter()
                .any(|(_, e)| matches!(e, Effect::SendItemReport { .. })),
            "{after:?}"
        );
        let ends: Vec<_> = after
            .iter()
            .filter(|(_, e)| matches!(e, Effect::EndHunter { .. }))
            .collect();
        assert_eq!(ends.len(), 1, "{after:?}");
        assert!(
            (exit + secs(55)..exit + secs(56)).contains(&ends[0].0),
            "ended {:?} after the exit",
            ends[0].0 - exit
        );
        assert!(reminder_texts(&m, exit + secs(70)).is_empty());
    }

    #[test]
    fn a_return_missed_for_good_drops_the_hunted_row() {
        let now = Instant::now();
        let mut m = running_items_machine(now);
        let t1 = now + ms(100);
        m.handle_message(hunter(13), t1);
        hunter_frames(&mut m, t1, t1 + secs(5), |_| true);
        let quit = t1 + secs(5);
        let exit = quit + secs(20);
        quit_out_load(&mut m, quit, secs(20));
        // Never found again: the row holds through the first miss (ended
        // 5.5 s after the exit: 2.5 s settle, 3 s look) and goes with the
        // third; no report goes out.
        let mut after = hunter_frames(&mut m, exit, exit + secs(8), |_| false);
        assert_eq!(
            after
                .iter()
                .filter(|(_, e)| matches!(e, Effect::EndHunter { .. }))
                .count(),
            1,
            "{after:?}"
        );
        assert_eq!(reminder_texts(&m, exit + secs(8)), ["Hunted"]);
        after.extend(hunter_frames(
            &mut m,
            exit + secs(8),
            exit + secs(20),
            |_| false,
        ));
        assert_eq!(
            after
                .iter()
                .filter(|(_, e)| matches!(e, Effect::EndHunter { .. }))
                .count(),
            3,
            "{after:?}"
        );
        assert!(
            !after
                .iter()
                .any(|(_, e)| matches!(e, Effect::SendItemReport { .. })),
            "{after:?}"
        );
        assert!(reminder_texts(&m, exit + secs(20)).is_empty());
    }

    #[test]
    fn only_a_quit_out_brings_the_hunter_back() {
        let now = Instant::now();
        let t1 = now + ms(100);
        let no_request = |steps: &[(Instant, Effect)]| {
            !steps
                .iter()
                .any(|(_, e)| matches!(e, Effect::RequestHunter { .. }))
        };

        // A fog gate while he hunts: gone at the first look after it, never
        // requested again.
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), t1);
        hunter_frames(&mut m, t1, t1 + secs(5), |_| true);
        let fx = load(&mut m, t1 + secs(5), secs(5), 61_000, true);
        let exit = t1 + secs(10);
        // The exit frame's look (he hunts, no settle) finds him gone.
        for effect in hunter_steps(fx) {
            assert!(matches!(effect, Effect::FindHunter { .. }), "{effect:?}");
            m.hunter_seen(false, exit);
        }
        let after = hunter_frames(&mut m, exit, exit + secs(30), |_| false);
        assert!(no_request(&after), "{after:?}");
        assert!(reminder_texts(&m, exit + secs(30)).is_empty());

        // A death or a fog gate on his way back after a quit-out: the hunt
        // ends at that exit, quietly, never requested.
        let mut m = running_items_machine(now);
        m.handle_message(hunter(13), t1);
        hunter_frames(&mut m, t1, t1 + secs(5), |_| true);
        let quit_exit = t1 + secs(25);
        quit_out_load(&mut m, t1 + secs(5), secs(20));
        hunter_frames(&mut m, quit_exit, quit_exit + secs(1), |_| true);
        let fx = load(&mut m, quit_exit + secs(1), secs(5), 61_000, true);
        let exit = quit_exit + secs(6);
        assert!(
            !fx.iter()
                .any(|e| matches!(e, Effect::SendItemReport { .. })),
            "{fx:?}"
        );
        assert!(reminder_texts(&m, exit).is_empty());
        let after = hunter_frames(&mut m, exit, exit + secs(30), |_| true);
        assert!(no_request(&after), "{after:?}");
    }

    #[test]
    fn the_hunter_is_ended_when_the_run_ends() {
        for end in ["finished", "new start", "another participant"] {
            let now = Instant::now();
            let mut m = running_items_machine(now);
            m.handle_message(hunter(13), now + ms(100));
            let t1 = now + ms(100);
            hunter_frames(&mut m, t1, t1 + secs(2), |_| true);

            let t2 = t1 + secs(2);
            let mut fx = Vec::new();
            match end {
                "new start" => {
                    fx.extend(m.handle_message(auth_ok_with_items("setup", true), t2));
                    fx.extend(m.handle_message(MachineMessage::RaceStart(0), t2 + ms(10)));
                }
                "another participant" => {
                    let mut other = auth_ok_with_items("running", true);
                    if let MachineMessage::AuthOk {
                        participant_id,
                        participants,
                        ..
                    } = &mut other
                    {
                        *participant_id = "p2".to_string();
                        participants[0] = test_participant("p2", "playing", 1);
                    }
                    fx.extend(m.handle_message(other, t2));
                }
                status => {
                    fx.extend(m.handle_message(
                        MachineMessage::LeaderboardUpdate {
                            participants: vec![test_participant("p1", status, 3)],
                            leader_splits: None,
                        },
                        t2,
                    ));
                }
            }
            // The next frames, a load and past his time: ended once, never
            // looked for again.
            let mut steps = hunter_steps(fx);
            steps.extend(
                hunter_frames(&mut m, t2 + ms(20), t2 + secs(2), |_| true)
                    .into_iter()
                    .map(|(_, e)| e),
            );
            // His row goes with him.
            assert!(reminder_texts(&m, t2 + secs(2)).is_empty(), "{end}");
            steps.extend(hunter_steps(load(
                &mut m,
                t2 + secs(3),
                secs(5),
                62_000,
                true,
            )));
            steps.extend(
                hunter_frames(&mut m, t2 + secs(8), t2 + secs(70), |_| true)
                    .into_iter()
                    .map(|(_, e)| e),
            );
            assert_eq!(
                steps,
                [Effect::EndHunter {
                    npc_param_id: HUNTER_ROW
                }],
                "{end}"
            );
        }
    }

    // ------------------------------------------------------------------
    // Relay roles and the team row
    // ------------------------------------------------------------------

    /// A relay's `RelayInfo` in the contract's full shape: me `p1`, teammate
    /// `p2` holding the baton, team `t1`, the team playing.
    fn relay_info_with(role: &str, team_status: &str) -> RelayInfo {
        let holder = if role == "holder" { "p1" } else { "p2" };
        serde_json::from_str(&format!(
            r#"{{"team_id":"t1","team_name":"Red Team","team_status":"{team_status}","cap":5,
              "holder_id":"{holder}","holder_online":true,"zone_name":"Stormveil Castle","baton_free_in_s":null,
              "role":"{role}","gates_locked":false,
              "members":[{{"participant_id":"p1","name":"Roger","zones":2,"status":"playing","online":true,"ready":true,"validated":true}},
                         {{"participant_id":"p2","name":"Kahleeya","zones":3,"status":"playing","online":true,"ready":false,"validated":true}}],
              "flags":{{"lock_flag":1050290500,"chapel_warp_flag":1050290501,"warp_flag_base":1050290510,"zone_flag_base":1050294000}}}}"#
        ))
        .unwrap()
    }

    fn relay_info(role: &str) -> RelayInfo {
        relay_info_with(role, "playing")
    }

    /// The setup shape: nobody holds the baton yet, everyone reads `waiting`.
    fn setup_relay_info() -> RelayInfo {
        let mut info = relay_info_with("waiting", "registered");
        info.holder_id = None;
        info.holder_online = false;
        info.zone_name = None;
        info.baton_free_in_s = Some(0);
        info
    }

    fn relay_auth(status: &str, relay: Option<RelayInfo>) -> MachineMessage {
        MachineMessage::AuthOk {
            participant_id: "p1".to_string(),
            race: test_race(status),
            seed: serde_json::from_str(
                r#"{"total_layers": 3, "event_ids": [1050294007], "finish_event": null,
                    "death_flags": {}, "boss_flags": [10000800]}"#,
            )
            .unwrap(),
            participants: vec![
                test_participant("t1", "playing", 2),
                test_participant("t2", "playing", 1),
            ],
            phantom_skin: None,
            latest_mod_version: None,
            held_item: None,
            relay,
        }
    }

    fn relay_machine(role: &str, now: Instant) -> RaceMachine {
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(relay_auth("running", Some(relay_info(role))), now);
        m
    }

    fn set_row_status(m: &mut RaceMachine, id: &str, status: &str) {
        m.handle_message(
            MachineMessage::PlayerUpdate(test_participant(id, status, 2)),
            Instant::now(),
        );
    }

    fn set_member_status(info: &mut RelayInfo, id: &str, status: ParticipantStatus) {
        info.members
            .iter_mut()
            .find(|member| member.participant_id == id)
            .unwrap()
            .status = status;
    }

    fn zone_data() -> ZoneUpdateData {
        ZoneUpdateData {
            display_name: "Stormveil Castle".into(),
            tier: Some(2),
            original_tier: None,
            layer: Some(2),
            is_first_visit: true,
            exits: Vec::new(),
            unused_exits: None,
            defeat_flag: None,
        }
    }

    #[test]
    fn a_relay_runner_reads_its_team_row() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        assert_eq!(m.my_participant().unwrap().id, "t1");
        assert_eq!(m.my_row_id(), Some("t1"));
        // The team row follows the runner whatever its place on the board.
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![
                    test_participant("t2", "playing", 3),
                    test_participant("t1", "playing", 2),
                ],
                leader_splits: None,
            },
            now,
        );
        assert_eq!(m.my_participant().unwrap().id, "t1");
        m.handle_message(
            MachineMessage::PlayerUpdate(test_participant("t1", "playing", 3)),
            now,
        );
        assert_eq!(m.pre_reveal_layer, Some(2));
    }

    #[test]
    fn a_leaderboard_update_of_the_team_row_freezes_the_layer_too() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        m.handle_message(
            MachineMessage::LeaderboardUpdate {
                participants: vec![
                    test_participant("t1", "playing", 3),
                    test_participant("t2", "playing", 1),
                ],
                leader_splits: None,
            },
            now,
        );
        assert_eq!(m.pre_reveal_layer, Some(2));
    }

    #[test]
    fn a_non_relay_runner_keeps_its_own_row() {
        let now = Instant::now();
        let m = running_machine(now);
        assert!(m.relay().is_none() && m.relay_role().is_none() && m.relay_me().is_none());
        assert_eq!(m.my_row_id(), Some("p1"));
        assert!(!m.relay_over() && !m.relay_live());
    }

    #[test]
    fn a_finished_team_finishes_every_member() {
        let now = Instant::now();
        let mut m = relay_machine("waiting", now);
        assert!(!m.am_i_finished());
        set_row_status(&mut m, "t1", "finished");
        assert!(m.am_i_finished());
    }

    #[test]
    fn an_abandoned_member_is_out_while_the_team_plays() {
        let now = Instant::now();
        for status in [
            ParticipantStatus::Abandoned,
            ParticipantStatus::Disqualified,
        ] {
            let mut m = relay_machine("waiting", now);
            assert!(!m.am_i_abandoned() && !m.relay_over());
            let mut info = relay_info("waiting");
            set_member_status(&mut info, "p1", status);
            m.handle_message(MachineMessage::RelayUpdate(info), now);
            assert_eq!(
                m.my_participant().unwrap().status,
                ParticipantStatus::Playing
            );
            assert!(m.am_i_abandoned(), "{status:?}");
            assert!(m.relay_over(), "{status:?}");
            assert!(!m.relay_live(), "{status:?}");
        }
    }

    #[test]
    fn a_teammate_out_does_not_end_my_relay() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        let mut info = relay_info("holder");
        set_member_status(&mut info, "p2", ParticipantStatus::Abandoned);
        m.handle_message(MachineMessage::RelayUpdate(info), now);
        assert!(!m.am_i_abandoned() && !m.relay_over());
        assert!(m.relay_live());
    }

    #[test]
    fn a_team_over_ends_the_relay() {
        let now = Instant::now();
        for status in ["finished", "abandoned", "disqualified"] {
            let mut m = relay_machine("holder", now);
            assert!(m.relay_live());
            m.handle_message(
                MachineMessage::RelayUpdate(relay_info_with("holder", status)),
                now,
            );
            assert!(m.relay_over(), "{status}");
            assert!(!m.relay_live(), "{status}");
        }
    }

    #[test]
    fn a_setup_relay_is_not_live() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(relay_auth("setup", Some(setup_relay_info())), now);
        assert!(!m.relay_live());
        m.handle_message(MachineMessage::RaceStart(10), now);
        assert!(m.is_race_running());
        assert!(!m.relay_live(), "the info still reads registered");
        m.handle_message(
            MachineMessage::RelayUpdate(relay_info_with("holder", "ready")),
            now,
        );
        assert!(m.relay_live(), "countdown");
        assert!(m.is_countdown_active(now));
        assert!(m.relay_live(), "after the countdown");
        m.handle_message(
            MachineMessage::RelayUpdate(relay_info_with("holder", "playing")),
            now,
        );
        assert!(m.relay_live());
    }

    #[test]
    fn a_relay_is_not_live_before_the_race_runs() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(relay_auth("setup", Some(relay_info("holder"))), now);
        assert!(!m.relay_live());
    }

    #[test]
    fn auth_ok_without_relay_forgets_the_team() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        let mut auth = relay_auth("running", None);
        if let MachineMessage::AuthOk { participants, .. } = &mut auth {
            *participants = vec![test_participant("p1", "playing", 1)];
        }
        m.handle_message(auth, now);
        assert!(m.relay().is_none());
        assert_eq!(m.my_participant().unwrap().id, "p1");
        assert_eq!(m.my_row_id(), Some("p1"));
    }

    #[test]
    fn auth_ok_replaces_the_team_whole() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        m.handle_message(relay_auth("running", Some(relay_info("waiting"))), now);
        assert_eq!(m.relay_role(), Some(RelayRole::Waiting));
    }

    #[test]
    fn becoming_a_waiting_runner_clears_the_zone() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        m.race_state.current_zone = Some(zone_data());
        m.pending_zone_update = Some(zone_data());
        let version = m.zone_version;
        m.handle_message(MachineMessage::RelayUpdate(relay_info("waiting")), now);
        assert!(m.race_state.current_zone.is_none());
        assert!(m.pending_zone_update.is_none());
        assert_eq!(m.zone_version, version + 1);
        // A further waiting update has nothing left to clear.
        m.handle_message(MachineMessage::RelayUpdate(relay_info("waiting")), now);
        assert_eq!(m.zone_version, version + 1);
    }

    #[test]
    fn an_unknown_role_keeps_the_zone_and_decides_nothing() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        m.race_state.current_zone = Some(zone_data());
        let version = m.zone_version;
        let mut info = relay_info("holder");
        info.role = RelayRole::Unknown;
        m.handle_message(MachineMessage::RelayUpdate(info), now);
        assert_eq!(m.relay_role(), Some(RelayRole::Unknown));
        assert!(m.race_state.current_zone.is_some());
        assert_eq!(m.zone_version, version);
        assert!(m.relay_live());
    }

    #[test]
    fn an_unknown_status_is_not_a_decision() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        let mut info = relay_info("holder");
        info.team_status = ParticipantStatus::Unknown;
        set_member_status(&mut info, "p1", ParticipantStatus::Unknown);
        m.handle_message(MachineMessage::RelayUpdate(info), now);
        // Neither over nor live: nothing is offered, nothing is ended.
        assert!(!m.relay_over());
        assert!(!m.relay_live());
        assert!(!m.am_i_abandoned());
        // An unknown member status alone leaves a live team live.
        let mut info = relay_info("holder");
        set_member_status(&mut info, "p1", ParticipantStatus::Unknown);
        m.handle_message(MachineMessage::RelayUpdate(info), now);
        assert!(!m.relay_over() && m.relay_live());
    }

    #[test]
    fn a_refusal_shows_its_message() {
        let now = Instant::now();
        let mut m = relay_machine("holder", now);
        m.handle_message(
            MachineMessage::RelayRefused {
                code: "target_at_cap".into(),
                message: "This teammate has reached their zone quota".into(),
            },
            now,
        );
        assert_eq!(
            m.get_status(now),
            Some("This teammate has reached their zone quota")
        );
    }

    #[test]
    fn a_waiting_runner_reports_its_own_save_after_the_countdown() {
        let now = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, now);
        m.handle_message(relay_auth("setup", Some(setup_relay_info())), now);
        m.handle_message(MachineMessage::RaceStart(10), now);
        m.handle_message(
            MachineMessage::RelayUpdate(relay_info_with("waiting", "ready")),
            now,
        );
        let status_igts = |fx: &[Effect]| -> Vec<u32> {
            fx.iter()
                .filter_map(|e| match e {
                    Effect::SendStatusUpdate { igt_ms, .. } => Some(*igt_ms),
                    _ => None,
                })
                .collect()
        };
        for t in [ms(200), secs(3), secs(9)] {
            let fx = m.tick(tick_in(snap(Some(5_000), true), true, None), now + t);
            assert!(status_igts(&fx).is_empty(), "countdown at {t:?}");
        }
        let fx = m.tick(
            tick_in(snap(Some(5_000), true), true, None),
            now + ms(10_300),
        );
        assert_eq!(status_igts(&fx), [5_000]);
    }

    // ------------------------------------------------------------------
    // Relay lock discipline, return to the Chapel, relay_ready
    // ------------------------------------------------------------------

    const LOCK: u32 = 1050290500;
    const CHAPEL_WARP: u32 = 1050290501;
    const IN_ZONE: u32 = 0x3C2C_2400;

    fn lock(value: bool) -> Effect {
        Effect::SetGameFlag {
            flag_id: LOCK,
            value,
        }
    }

    fn warp(value: bool) -> Effect {
        Effect::SetGameFlag {
            flag_id: CHAPEL_WARP,
            value,
        }
    }

    fn ready(value: bool) -> Effect {
        Effect::SendRelayReady { ready: value }
    }

    /// One connected frame `at` ms after `t0`: loaded on `map`, or an
    /// unreadable position (a loading screen) on `None`. The IGT follows the
    /// clock, so nothing reads as a reload.
    fn go(m: &mut RaceMachine, t0: Instant, at: u64, map: Option<u32>) -> Vec<Effect> {
        let snapshot = FrameSnapshot {
            igt_ms: Some(5_000 + at as u32),
            death_count: Some(0),
            position_readable: map.is_some(),
            loading_screen: Some(false),
            map_id: map,
            hp: map.map(|_| 100),
            ..FrameSnapshot::default()
        };
        m.tick(tick_in(snapshot, true, None), t0 + ms(at))
    }

    /// Frames every 100 ms over `[from, to]` on `map`, the effects tagged
    /// with their time.
    fn go_over(
        m: &mut RaceMachine,
        t0: Instant,
        from: u64,
        to: u64,
        map: Option<u32>,
    ) -> Vec<(u64, Effect)> {
        let mut out = Vec::new();
        let mut at = from;
        while at <= to {
            out.extend(go(m, t0, at, map).into_iter().map(|e| (at, e)));
            at += 100;
        }
        out
    }

    /// A loading screen at `at` and the exit 16 ms later; returns the exit's
    /// time.
    fn load_in(m: &mut RaceMachine, t0: Instant, at: u64, map: u32) -> u64 {
        let fx = go(m, t0, at, None);
        assert!(!fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })));
        let fx = go(m, t0, at + 16, Some(map));
        assert!(
            !fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })),
            "a relay flag written on the unsettled exit frame: {fx:?}"
        );
        at + 16
    }

    /// The loading exit frame itself: nothing is written on it.
    fn go_exit(m: &mut RaceMachine, t0: Instant, at: u64, map: Option<u32>) {
        let fx = go(m, t0, at, map);
        assert!(
            !fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })),
            "a flag written on the unsettled exit frame: {fx:?}"
        );
    }

    /// Frames every 100 ms from `from` in the zone until the warp flag is
    /// raised; returns when.
    fn run_until_warp(m: &mut RaceMachine, t0: Instant, from: u64) -> u64 {
        let mut at = from;
        while at <= from + 20_000 {
            if go(m, t0, at, Some(IN_ZONE)).contains(&warp(true)) {
                return at;
            }
            at += 100;
        }
        panic!("no warp raised");
    }

    fn times_of(fx: &[(u64, Effect)], wanted: &Effect) -> Vec<u64> {
        fx.iter()
            .filter(|(_, e)| e == wanted)
            .map(|(at, _)| *at)
            .collect()
    }

    fn any_relay_write(fx: &[Effect]) -> bool {
        fx.iter().any(|e| {
            matches!(e, Effect::SetGameFlag { flag_id, .. }
                if (LOCK..=LOCK + 20).contains(flag_id))
                || matches!(e, Effect::SendRelayReady { .. })
        })
    }

    fn settle_ms() -> u64 {
        crate::core::relay::SETTLE.as_millis() as u64
    }

    fn chapel() -> Option<u32> {
        Some(crate::core::relay::CHAPEL_MAP_ID)
    }

    fn update(m: &mut RaceMachine, info: RelayInfo, t0: Instant, at: u64) {
        m.handle_message(MachineMessage::RelayUpdate(info), t0 + ms(at));
    }

    #[test]
    fn a_waiting_runner_is_locked_once_loaded_and_settled() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let exit = load_in(&mut m, t0, 100, IN_ZONE);
        let fx = go_over(
            &mut m,
            t0,
            exit + 100,
            exit + settle_ms() + 1_000,
            Some(IN_ZONE),
        );
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
        let at = fx.iter().find(|(_, e)| *e == lock(true)).unwrap().0;
        assert!(
            at >= exit + settle_ms() && at < exit + settle_ms() + 100,
            "{at}"
        );
        assert_eq!(m.relay_locked(), Some(true));
    }

    #[test]
    fn the_lock_is_never_written_during_a_load() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, None);
        update(&mut m, relay_info("waiting"), t0, 10);
        for i in 1..=10 {
            let fx = go(&mut m, t0, 10 + i * 100, None);
            assert!(
                !fx.iter().any(|e| matches!(e, Effect::SetGameFlag { .. })),
                "{i}"
            );
        }
        let exit = 1_200;
        go_exit(&mut m, t0, exit, chapel());
        let fx = go_over(&mut m, t0, exit + 100, exit + settle_ms() + 200, chapel());
        let at = times_of(&fx, &lock(true));
        assert_eq!(at.len(), 1);
        assert!(at[0] >= exit + settle_ms());
    }

    #[test]
    fn the_lock_is_asserted_again_after_each_loading_exit() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let e1 = load_in(&mut m, t0, 100, chapel().unwrap());
        let fx = go_over(&mut m, t0, e1 + 100, e1 + 3_000, chapel());
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
        let e2 = load_in(&mut m, t0, 4_000, chapel().unwrap());
        let fx = go_over(&mut m, t0, e2 + 100, e2 + 3_000, chapel());
        let at = times_of(&fx, &lock(true));
        assert_eq!(at.len(), 1);
        assert!(at[0] >= e2 + settle_ms());
    }

    #[test]
    fn a_relaunched_holder_drops_a_stale_lock() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        let fx = go_over(&mut m, t0, 0, 2_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(false)), [0]);
        assert!(times_of(&fx, &lock(true)).is_empty());
        assert_eq!(m.relay_locked(), Some(false));
    }

    #[test]
    fn a_relaunched_waiting_runner_raises_the_lock_its_save_may_hold() {
        // The machine cannot know the flag's state: it writes what the
        // server says, once, whatever the save holds.
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 2_000, chapel());
        assert_eq!(times_of(&fx, &lock(true)), [0]);
    }

    #[test]
    fn a_capped_holder_is_locked_and_told_once() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        let mut capped = relay_info("holder");
        capped.gates_locked = true;
        update(&mut m, capped.clone(), t0, 100);
        let fx = go(&mut m, t0, 200, Some(IN_ZONE));
        assert!(fx.contains(&lock(true)), "{fx:?}");
        assert_eq!(
            m.item_banner().unwrap().title,
            "QUOTA REACHED: PASS THE BATON"
        );
        // Shown and gone: an identical update tells nothing again.
        let later = t0 + secs(30);
        m.item_feed.advance(later, Duration::ZERO);
        assert!(m.item_banner().is_none());
        m.handle_message(MachineMessage::RelayUpdate(capped), later);
        go(&mut m, t0, 30_100, Some(IN_ZONE));
        assert!(m.item_banner().is_none());
    }

    #[test]
    fn the_start_locks_only_after_the_relay_update() {
        for (role, locks) in [("waiting", true), ("holder", false)] {
            let t0 = Instant::now();
            let mut m = RaceMachine::new(1, String::new(), false, t0);
            m.handle_message(relay_auth("setup", Some(setup_relay_info())), t0);
            let fx = go_over(&mut m, t0, 0, 1_000, chapel());
            assert!(!fx
                .iter()
                .any(|(_, e)| *e == lock(true) || *e == ready(true)));
            m.handle_message(MachineMessage::RaceStart(10), t0 + ms(1_000));
            let fx = go_over(&mut m, t0, 1_100, 4_000, chapel());
            assert!(
                !fx.iter()
                    .any(|(_, e)| *e == lock(true) || *e == ready(true)),
                "{role}"
            );
            let start = relay_info_with(role, "ready");
            update(&mut m, start, t0, 4_050);
            let fx = go_over(&mut m, t0, 4_100, 6_000, chapel());
            assert_eq!(
                times_of(&fx, &lock(true)).len(),
                usize::from(locks),
                "{role}"
            );
            assert_eq!(
                times_of(&fx, &ready(true)).len(),
                usize::from(locks),
                "{role}"
            );
            if locks {
                assert_eq!(times_of(&fx, &lock(true)), [4_100]);
            } else {
                assert!(!fx.iter().any(|(_, e)| *e == ready(true)));
            }
        }
    }

    #[test]
    fn the_start_update_in_a_loading_screen_waits_for_the_settle() {
        let t0 = Instant::now();
        let mut m = RaceMachine::new(1, String::new(), false, t0);
        m.handle_message(relay_auth("setup", Some(setup_relay_info())), t0);
        go(&mut m, t0, 0, chapel());
        m.handle_message(MachineMessage::RaceStart(10), t0 + ms(100));
        go(&mut m, t0, 200, None);
        update(&mut m, relay_info_with("waiting", "ready"), t0, 300);
        let fx = go_over(&mut m, t0, 300, 1_900, None);
        assert!(fx.is_empty(), "{fx:?}");
        let exit = 2_000;
        go_exit(&mut m, t0, exit, chapel());
        let fx = go_over(&mut m, t0, exit + 100, exit + settle_ms() + 200, chapel());
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
        assert!(times_of(&fx, &lock(true))[0] >= exit + settle_ms());
    }

    #[test]
    fn the_lock_follows_the_server_both_ways() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go_over(&mut m, t0, 0, 300, Some(IN_ZONE));
        update(&mut m, relay_info("waiting"), t0, 400);
        let fx = go_over(&mut m, t0, 400, 2_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(true)), [400]);
        assert!(
            times_of(&fx, &warp(true)).is_empty(),
            "inside the gate window"
        );
        update(&mut m, relay_info("holder"), t0, 2_050);
        let fx = go_over(&mut m, t0, 2_100, 12_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(false)), [2_100]);
        assert!(!fx.iter().any(|(_, e)| *e == warp(true)));
        assert_eq!(m.relay_locked(), Some(false));
    }

    /// A machine locked and ready at the Chapel, the window long over.
    fn locked_at_chapel(t0: Instant) -> RaceMachine {
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 300, chapel());
        assert!(fx.iter().any(|(_, e)| *e == lock(true)));
        assert!(fx.iter().any(|(_, e)| *e == ready(true)));
        m
    }

    #[test]
    fn the_lock_is_lowered_when_the_runners_race_is_over() {
        type Case = (&'static str, Box<dyn Fn(&mut RaceMachine, Instant)>);
        let cases: Vec<Case> = vec![
            (
                "team finished",
                Box::new(|m, t| update(m, relay_info_with("waiting", "finished"), t, 1_000)),
            ),
            (
                "team abandoned",
                Box::new(|m, t| update(m, relay_info_with("waiting", "abandoned"), t, 1_000)),
            ),
            (
                "team disqualified",
                Box::new(|m, t| update(m, relay_info_with("waiting", "disqualified"), t, 1_000)),
            ),
            (
                "member abandoned",
                Box::new(|m, t| {
                    let mut i = relay_info("waiting");
                    set_member_status(&mut i, "p1", ParticipantStatus::Abandoned);
                    update(m, i, t, 1_000)
                }),
            ),
            (
                "member disqualified",
                Box::new(|m, t| {
                    let mut i = relay_info("waiting");
                    set_member_status(&mut i, "p1", ParticipantStatus::Disqualified);
                    update(m, i, t, 1_000)
                }),
            ),
            (
                "race finished",
                Box::new(|m, t| {
                    m.handle_message(
                        MachineMessage::RaceStatusChange {
                            status: RaceStatus::Finished,
                            current_igt: None,
                        },
                        t + ms(1_000),
                    );
                }),
            ),
            (
                "race reset (auth_ok)",
                Box::new(|m, t| {
                    m.handle_message(relay_auth("setup", Some(setup_relay_info())), t + ms(1_000));
                }),
            ),
            (
                "race back to setup",
                Box::new(|m, t| {
                    m.handle_message(
                        MachineMessage::RaceInfoUpdate(test_race("setup")),
                        t + ms(1_000),
                    );
                }),
            ),
        ];
        for (name, event) in cases {
            for warping in [false, true] {
                let t0 = Instant::now();
                let mut m = locked_at_chapel(t0);
                if warping {
                    // Away from the Chapel, past the window: a warp raised.
                    let fx = go_over(&mut m, t0, 400, 6_000, Some(IN_ZONE));
                    assert_eq!(times_of(&fx, &warp(true)).len(), 1, "{name}");
                }
                event(&mut m, t0);
                // At the Chapel, ready until the end tells it otherwise; away
                // from it, with a warp on its way, already not ready.
                let map = if warping { Some(IN_ZONE) } else { chapel() };
                let fx = go_over(&mut m, t0, 6_100, 12_000, map);
                assert_eq!(times_of(&fx, &lock(false)), [6_100], "{name} {warping}");
                assert!(!fx.iter().any(|(_, e)| *e == warp(true)), "{name}");
                assert!(!fx.iter().any(|(_, e)| *e == ready(true)), "{name}");
                // An auth_ok sends the value again whatever it was.
                let again = !warping || name.contains("auth_ok");
                let not_ready: &[u64] = if again { &[6_100] } else { &[] };
                assert_eq!(times_of(&fx, &ready(false)), not_ready, "{name}");
                assert_eq!(m.relay_locked(), Some(false), "{name}");
            }
        }
    }

    #[test]
    fn a_warp_flag_still_raised_is_lowered_when_the_relay_ends() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let fx = go_over(&mut m, t0, 400, 5_600, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &warp(true)).len(), 1);
        update(&mut m, relay_info("holder"), t0, 5_650);
        let fx = go(&mut m, t0, 5_700, Some(IN_ZONE));
        assert!(fx.contains(&warp(false)), "{fx:?}");
        assert!(fx.contains(&lock(false)));
        let fx = go_over(&mut m, t0, 5_800, 20_000, Some(IN_ZONE));
        assert!(!fx.iter().any(|(_, e)| *e == warp(true)));
    }

    #[test]
    fn a_waiting_runner_away_from_the_chapel_is_sent_back_after_the_gate_window() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go_over(&mut m, t0, 0, 300, Some(IN_ZONE));
        update(&mut m, relay_info("waiting"), t0, 400);
        let fx = go_over(&mut m, t0, 400, 9_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(true)), [400]);
        assert_eq!(times_of(&fx, &warp(true)), [5_400]);
        // Away from the Chapel it is never ready.
        assert!(times_of(&fx, &ready(true)).is_empty());
    }

    #[test]
    fn a_loading_exit_after_the_lock_closes_the_gate_window() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go_over(&mut m, t0, 0, 300, Some(IN_ZONE));
        update(&mut m, relay_info("waiting"), t0, 400);
        go_over(&mut m, t0, 400, 1_000, Some(IN_ZONE));
        let exit = load_in(&mut m, t0, 1_100, IN_ZONE);
        let fx = go_over(&mut m, t0, exit + 100, exit + 4_000, Some(IN_ZONE));
        let at = times_of(&fx, &warp(true));
        assert_eq!(at.len(), 1, "{fx:?}");
        assert!(
            at[0] >= exit + settle_ms() && at[0] < exit + settle_ms() + 100,
            "{at:?}"
        );
    }

    #[test]
    fn a_dead_runner_is_not_warped() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go_over(&mut m, t0, 0, 300, Some(IN_ZONE));
        update(&mut m, relay_info("waiting"), t0, 400);
        let frame = |m: &mut RaceMachine, at: u64, hp: i32| {
            let snapshot = FrameSnapshot {
                igt_ms: Some(5_000 + at as u32),
                death_count: Some(0),
                position_readable: true,
                loading_screen: Some(false),
                map_id: Some(IN_ZONE),
                hp: Some(hp),
                ..FrameSnapshot::default()
            };
            m.tick(tick_in(snapshot, true, None), t0 + ms(at))
        };
        for at in (400..=7_000).step_by(100) {
            let fx = frame(&mut m, at, 0);
            assert!(!fx.contains(&warp(true)), "{at}");
        }
        assert!(frame(&mut m, 7_100, 1).contains(&warp(true)));
    }

    #[test]
    fn hp_is_asked_only_while_the_return_to_the_chapel_may_start() {
        let t0 = Instant::now();
        let hp = |m: &RaceMachine, at: u64| m.pre_tick(t0 + ms(at), true, true).hp;
        let mut m = relay_machine("holder", t0);
        go_over(&mut m, t0, 0, 300, Some(IN_ZONE));
        assert!(!hp(&m, 400), "a holder");
        update(&mut m, relay_info("waiting"), t0, 400);
        go_over(&mut m, t0, 400, 5_300, Some(IN_ZONE));
        assert!(!hp(&m, 5_300), "inside the gate window");
        assert!(hp(&m, 5_400), "the warp may start");
        go(&mut m, t0, 5_400, Some(IN_ZONE));
        assert!(!hp(&m, 5_500), "a warp running does not use it");
        // Given up after two landings away from the Chapel.
        let exit = load_in(&mut m, t0, 5_500, IN_ZONE);
        let at = run_until_warp(&mut m, t0, exit + 100) + 100;
        let exit = load_in(&mut m, t0, at, IN_ZONE);
        go_over(&mut m, t0, exit + 100, exit + 6_000, Some(IN_ZONE));
        assert!(!hp(&m, exit + 6_100), "given up for good");
        let m = locked_at_chapel(Instant::now());
        assert!(!m.pre_tick(Instant::now(), true, true).hp, "at the Chapel");
    }

    #[test]
    fn a_warp_that_never_loads_gives_up_with_a_status() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let fx = go_over(&mut m, t0, 400, 30_000, Some(IN_ZONE));
        let raises = times_of(&fx, &warp(true));
        assert_eq!(raises.len(), 3);
        // The flag is lowered between raises and once more when given up,
        // five seconds after the last raise, with the status.
        let failed = raises[2] + 5_000;
        let lowers = times_of(&fx, &warp(false));
        assert_eq!(lowers, [raises[0] + 5_000, raises[1] + 5_000, failed]);
        assert_eq!(
            m.get_status(t0 + ms(failed)),
            Some("Warp to the Chapel failed")
        );
    }

    #[test]
    fn the_return_to_the_chapel_end_to_end() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 6_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &warp(true)), [5_000]);
        // The seed warps: a load, ending at the Chapel.
        let exit = load_in(&mut m, t0, 5_100, crate::core::relay::CHAPEL_MAP_ID);
        let fx = go_over(&mut m, t0, exit + 100, exit + 8_000, chapel());
        assert!(times_of(&fx, &warp(true)).is_empty(), "no second raise");
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
        let ready_at = times_of(&fx, &ready(true));
        assert_eq!(ready_at.len(), 1);
        assert!(ready_at[0] >= exit + settle_ms());
    }

    #[test]
    fn no_relay_flag_is_written_on_the_exit_frame() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        go(&mut m, t0, 500, None);
        // The server's word changes during the load.
        update(&mut m, relay_info("holder"), t0, 550);
        go_exit(&mut m, t0, 600, chapel());
        let fx = go_over(&mut m, t0, 700, 600 + settle_ms() + 100, chapel());
        assert_eq!(times_of(&fx, &lock(false)).len(), 1);
        assert!(times_of(&fx, &lock(false))[0] >= 600 + settle_ms());
    }

    #[test]
    fn a_waiting_runner_turning_holder_at_the_chapel_is_no_longer_ready() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        update(&mut m, relay_info("holder"), t0, 400);
        let fx = go(&mut m, t0, 500, chapel());
        assert!(fx.contains(&ready(false)), "{fx:?}");
        assert!(fx.contains(&lock(false)));
    }

    #[test]
    fn two_landings_away_from_the_chapel_end_the_return_for_good() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let mut at = 400;
        let mut exit = 0;
        for _ in 0..2 {
            let raise = run_until_warp(&mut m, t0, at);
            exit = load_in(&mut m, t0, raise + 100, IN_ZONE);
            at = exit + 100;
        }
        assert_eq!(
            m.get_status(t0 + ms(exit)),
            Some("Warp to the Chapel failed")
        );
        // No third raise, however many loads come.
        for _ in 0..3 {
            let fx = go_over(&mut m, t0, at, at + 15_000, Some(IN_ZONE));
            assert!(times_of(&fx, &warp(true)).is_empty());
            assert!(times_of(&fx, &ready(true)).is_empty());
            exit = load_in(&mut m, t0, at + 15_100, IN_ZONE);
            at = exit + 100;
        }
        assert_eq!(m.relay_warp_landings, 2);
    }

    #[test]
    fn reaching_the_chapel_resets_the_landing_count() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let raise = run_until_warp(&mut m, t0, 400);
        let exit = load_in(&mut m, t0, raise + 100, IN_ZONE);
        go_over(&mut m, t0, exit + 100, exit + 100, Some(IN_ZONE));
        assert_eq!(m.relay_warp_landings, 1);
        let exit = load_in(&mut m, t0, exit + 200, crate::core::relay::CHAPEL_MAP_ID);
        go(&mut m, t0, exit + 100, chapel());
        assert_eq!(m.relay_warp_landings, 0);
        // Two more landings are needed again before giving up.
        let mut at = exit + 200;
        for n in 1..=2 {
            let exit = load_in(&mut m, t0, at, IN_ZONE);
            let raise = run_until_warp(&mut m, t0, exit + 100);
            let exit = load_in(&mut m, t0, raise + 100, IN_ZONE);
            go(&mut m, t0, exit + 100, Some(IN_ZONE));
            assert_eq!(m.relay_warp_landings, n);
            at = exit + 200;
        }
    }

    #[test]
    fn the_lock_going_down_resets_the_landing_count() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let mut at = 400;
        for _ in 0..2 {
            let raise = run_until_warp(&mut m, t0, at);
            let exit = load_in(&mut m, t0, raise + 100, IN_ZONE);
            at = exit + 100;
        }
        assert_eq!(m.relay_warp_landings, 2);
        update(&mut m, relay_info("holder"), t0, at);
        let fx = go_over(&mut m, t0, at + 100, at + 3_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(false)).len(), 1);
        assert_eq!(m.relay_warp_landings, 0);
        // Waiting again: the return works once more.
        update(&mut m, relay_info("waiting"), t0, at + 3_100);
        run_until_warp(&mut m, t0, at + 3_100);
    }

    #[test]
    fn a_load_in_the_gap_between_a_lower_and_a_raise_never_raises_on_an_unsettled_frame() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 10_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &warp(true)), [5_000]);
        assert_eq!(times_of(&fx, &warp(false)), [10_000]);
        // The load starts inside the 100 ms the flag stays down.
        let exit = load_in(&mut m, t0, 10_050, IN_ZONE);
        let fx = go_over(
            &mut m,
            t0,
            exit + 100,
            exit + settle_ms() + 100,
            Some(IN_ZONE),
        );
        let raises = times_of(&fx, &warp(true));
        assert_eq!(raises.len(), 1, "{fx:?}");
        assert!(raises[0] >= exit + settle_ms());
    }

    #[test]
    fn a_warp_that_lands_at_the_chapel_without_a_load_frame_ends() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 5_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &warp(true)), [5_000]);
        let fx = go(&mut m, t0, 5_100, chapel());
        assert!(fx.contains(&warp(false)), "{fx:?}");
        let fx = go_over(&mut m, t0, 5_200, 15_000, chapel());
        assert!(times_of(&fx, &warp(true)).is_empty());
        assert_eq!(m.relay_warp_landings, 0);
    }

    #[test]
    fn a_fresh_holder_with_an_unknown_team_status_drops_a_stale_lock() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        let mut info = relay_info("holder");
        info.team_status = ParticipantStatus::Unknown;
        update(&mut m, info, t0, 0);
        let fx = go_over(&mut m, t0, 0, 500, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(false)), [0]);
        // A capped holder, or any other role, is left alone.
        for (role, capped) in [("holder", true), ("waiting", false)] {
            let mut m = relay_machine(role, t0);
            let mut info = relay_info(role);
            info.team_status = ParticipantStatus::Unknown;
            info.gates_locked = capped;
            update(&mut m, info, t0, 0);
            let fx = go_over(&mut m, t0, 0, 500, Some(IN_ZONE));
            assert!(!fx
                .iter()
                .any(|(_, e)| matches!(e, Effect::SetGameFlag { .. })));
        }
    }

    #[test]
    fn relay_ready_follows_the_chapel_and_the_lock() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let fx = go_over(&mut m, t0, 0, 500, chapel());
        assert_eq!(times_of(&fx, &ready(true)), [0]);
        // A loading screen: not loaded, not ready.
        let fx = go(&mut m, t0, 600, None);
        assert_eq!(fx, vec![ready(false)]);
        assert!(go(&mut m, t0, 700, None).is_empty());
        // Back: ready once the lock is asserted again.
        let exit = 800;
        go_exit(&mut m, t0, exit, chapel());
        let fx = go_over(&mut m, t0, exit + 100, exit + 3_000, chapel());
        let at = times_of(&fx, &ready(true));
        assert_eq!(at.len(), 1);
        assert!(at[0] >= exit + settle_ms());
        // Reconnection while at the Chapel: the current value again, once.
        m.handle_message(
            relay_auth("running", Some(relay_info("waiting"))),
            t0 + secs(5),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + secs(5),
        );
        let fx = go_over(&mut m, t0, 5_100, 5_500, chapel());
        assert_eq!(times_of(&fx, &ready(true)), [5_100]);
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::SetGameFlag { .. })));
        // Away from the Chapel: false, and false again after a reconnection.
        let fx = go_over(&mut m, t0, 5_600, 5_800, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &ready(false)), [5_600]);
        m.handle_message(
            relay_auth("running", Some(relay_info("waiting"))),
            t0 + secs(6),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + secs(6),
        );
        let fx = go_over(&mut m, t0, 6_100, 6_500, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &ready(false)), [6_100]);
        assert!(times_of(&fx, &ready(true)).is_empty());
    }

    #[test]
    fn a_holder_never_sends_ready_true() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        let fx = go_over(&mut m, t0, 0, 5_000, chapel());
        assert!(times_of(&fx, &ready(true)).is_empty());
        assert_eq!(times_of(&fx, &ready(false)), [0]);
    }

    #[test]
    fn a_socket_reconnect_while_locked_keeps_the_lock() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        // The auth_ok info reads the runner not ready; the update follows.
        let mut info = relay_info("waiting");
        info.members[0].ready = false;
        m.handle_message(relay_auth("running", Some(info)), t0 + secs(2));
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + secs(2),
        );
        update(&mut m, relay_info("waiting"), t0, 2_050);
        let fx = go_over(&mut m, t0, 2_100, 3_000, chapel());
        assert!(
            !fx.iter()
                .any(|(_, e)| matches!(e, Effect::SetGameFlag { .. })),
            "{fx:?}"
        );
        assert_eq!(times_of(&fx, &ready(true)), [2_100]);
        assert_eq!(m.relay_locked(), Some(true));
    }

    #[test]
    fn an_unknown_role_or_team_status_keeps_the_lock_state_and_offers_nothing() {
        for locked in [true, false] {
            for what in ["role", "team"] {
                let t0 = Instant::now();
                let mut m = relay_machine(if locked { "waiting" } else { "holder" }, t0);
                go_over(&mut m, t0, 0, 400, chapel());
                let before = m.relay_locked();
                let mut info = relay_info(if locked { "waiting" } else { "holder" });
                if what == "role" {
                    info.role = RelayRole::Unknown;
                } else {
                    info.team_status = ParticipantStatus::Unknown;
                }
                update(&mut m, info, t0, 450);
                // Past the window, away from the Chapel, after a load.
                let exit = load_in(&mut m, t0, 500, IN_ZONE);
                let fx = go_over(&mut m, t0, exit + 100, exit + 9_000, Some(IN_ZONE));
                assert!(
                    !fx.iter()
                        .any(|(_, e)| matches!(e, Effect::SetGameFlag { flag_id, .. }
                        if *flag_id == CHAPEL_WARP)),
                    "{what} {locked}"
                );
                assert!(
                    !fx.iter().any(|(_, e)| *e == lock(!before.unwrap())),
                    "{what} {locked}"
                );
                assert!(
                    !fx.iter().any(|(_, e)| *e == ready(true)),
                    "{what} {locked}"
                );
                assert_eq!(m.relay_locked(), before);
            }
        }
    }

    #[test]
    fn an_unknown_role_does_not_outweigh_a_finished_team() {
        let t0 = Instant::now();
        let mut m = locked_at_chapel(t0);
        let mut info = relay_info_with("waiting", "finished");
        info.role = RelayRole::Unknown;
        update(&mut m, info, t0, 400);
        let fx = go_over(&mut m, t0, 500, 800, chapel());
        assert_eq!(times_of(&fx, &lock(false)), [500]);
    }

    #[test]
    fn a_wrong_save_writes_no_relay_flag() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        m.wrong_save = true;
        let fx = go_over(&mut m, t0, 0, 5_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::SetGameFlag { .. })));
        assert!(!fx.iter().any(|(_, e)| *e == ready(true)));
    }

    #[test]
    fn a_race_without_relay_writes_no_relay_flag() {
        let t0 = Instant::now();
        let mut m = running_machine(t0);
        for at in (0..=5_000).step_by(100) {
            let fx = go(&mut m, t0, at, Some(IN_ZONE));
            assert!(!any_relay_write(&fx), "{at}");
        }
        assert!(!m.pre_tick(t0 + ms(5_100), true, true).hp);
        assert_eq!(m.relay_locked(), None);
    }

    #[test]
    fn the_runner_absent_from_its_team_is_neither_out_nor_over() {
        let t0 = Instant::now();
        let mut m = relay_machine("waiting", t0);
        let mut info = relay_info("waiting");
        info.members.retain(|member| member.participant_id != "p1");
        set_member_status(&mut info, "p2", ParticipantStatus::Abandoned);
        update(&mut m, info, t0, 100);
        assert!(m.relay_me().is_none());
        assert!(!m.am_i_abandoned() && !m.relay_over());
        assert!(m.relay_live());
        // And a later update naming it again is read.
        let mut back = relay_info("waiting");
        set_member_status(&mut back, "p1", ParticipantStatus::Abandoned);
        update(&mut m, back, t0, 200);
        assert!(m.am_i_abandoned() && m.relay_over() && !m.relay_live());
    }

    // ------------------------------------------------------------------
    // Giving the baton: the release capture and the zone checkpoints
    // ------------------------------------------------------------------

    fn captures(fx: &[Effect]) -> Vec<Option<String>> {
        fx.iter()
            .filter_map(|e| match e {
                Effect::CaptureRelayState { handoff_id } => Some(handoff_id.clone()),
                _ => None,
            })
            .collect()
    }

    fn sent_states(fx: &[Effect]) -> Vec<&Effect> {
        fx.iter()
            .filter(|e| matches!(e, Effect::SendRelayState { .. }))
            .collect()
    }

    fn char_state() -> CharacterState {
        CharacterState {
            attributes: [20, 15, 18, 16, 14, 9, 8, 7],
            level: 30,
            runes: 1234,
            items: vec![2_000_005, 0x4000_0001],
            grace_flags: vec![71800],
        }
    }

    fn release(m: &mut RaceMachine, t0: Instant, at: u64, id: &str) {
        m.handle_message(
            MachineMessage::RelayRelease {
                handoff_id: id.to_string(),
                to_name: "Kahleeya".to_string(),
            },
            t0 + ms(at),
        );
    }

    fn frame(
        m: &mut RaceMachine,
        t0: Instant,
        at: u64,
        map: Option<u32>,
        connected: bool,
    ) -> Vec<Effect> {
        let snapshot = FrameSnapshot {
            igt_ms: Some(5_000 + at as u32),
            death_count: Some(0),
            position_readable: map.is_some(),
            loading_screen: Some(false),
            map_id: map,
            hp: map.map(|_| 100),
            ..FrameSnapshot::default()
        };
        m.tick(tick_in(snapshot, connected, None), t0 + ms(at))
    }

    fn answer(
        m: &mut RaceMachine,
        t0: Instant,
        at: u64,
        id: Option<&str>,
        state: Option<CharacterState>,
    ) -> Vec<Effect> {
        m.relay_state_captured(id.map(str::to_string), state, t0 + ms(at))
    }

    /// A holder on a loaded frame at 0 (the loading exit), the release
    /// asked and its capture in flight at 100.
    fn holder_with_capture_in_flight() -> (RaceMachine, Instant) {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        release(&mut m, t0, 50, "h1");
        let fx = go(&mut m, t0, 100, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
        (m, t0)
    }

    #[test]
    fn a_release_captures_on_a_loaded_frame_and_answers_with_the_state() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, None);
        release(&mut m, t0, 50, "h1");
        for at in [100, 200, 300] {
            assert!(captures(&go(&mut m, t0, at, None)).is_empty(), "{at}");
        }
        let fx = go(&mut m, t0, 400, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
        for at in [500, 600] {
            let fx = go(&mut m, t0, at, Some(IN_ZONE));
            assert!(captures(&fx).is_empty(), "one capture at a time: {at}");
        }
        let fx = answer(&mut m, t0, 700, Some("h1"), Some(char_state()));
        assert_eq!(
            fx,
            [Effect::SendRelayState {
                handoff_id: Some("h1".to_string()),
                state: char_state(),
                igt_ms: 5_000 + 600,
            }]
        );
        assert!(m.item_banner().is_none());
        assert_ne!(m.relay_locked(), Some(true));
    }

    #[test]
    fn the_giver_is_locked_only_once_the_server_flips_the_role() {
        let (mut m, t0) = holder_with_capture_in_flight();
        answer(&mut m, t0, 150, Some("h1"), Some(char_state()));
        let fx = go_over(&mut m, t0, 200, 6_000, Some(IN_ZONE));
        assert!(!fx.iter().any(|(_, e)| *e == lock(true) || *e == warp(true)));
        assert!(m.item_banner().is_none());

        update(&mut m, relay_info("waiting"), t0, 6_050);
        assert_eq!(m.item_banner().unwrap().title, "BATON PASSED TO KAHLEEYA");
        assert_eq!(m.item_banner().unwrap().line, "");
        let fx = go_over(&mut m, t0, 6_100, 14_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
        let lock_at = times_of(&fx, &lock(true))[0];
        let warp_at = times_of(&fx, &warp(true));
        assert_eq!(warp_at.len(), 1);
        assert!(
            warp_at[0] >= lock_at + crate::core::relay::GATE_WINDOW.as_millis() as u64,
            "{lock_at} {warp_at:?}"
        );
    }

    #[test]
    fn a_release_the_server_drops_changes_nothing() {
        let (mut m, t0) = holder_with_capture_in_flight();
        answer(&mut m, t0, 150, Some("h1"), Some(char_state()));
        // The server's answer to an expired handoff: still the holder.
        update(&mut m, relay_info("holder"), t0, 1_000);
        let fx = go_over(&mut m, t0, 1_100, 12_000, Some(IN_ZONE));
        assert!(!fx.iter().any(|(_, e)| *e == lock(true) || *e == warp(true)));
        assert!(m.item_banner().is_none());
        // 16 s after the answer a takeover turns the runner waiting.
        update(&mut m, relay_info("waiting"), t0, 16_200);
        assert!(m.item_banner().is_none(), "no BATON PASSED for a takeover");
        let fx = go_over(&mut m, t0, 16_300, 17_000, Some(IN_ZONE));
        assert_eq!(times_of(&fx, &lock(true)).len(), 1);
    }

    #[test]
    fn a_flip_inside_the_release_window_shows_the_banner() {
        let (mut m, t0) = holder_with_capture_in_flight();
        answer(&mut m, t0, 150, Some("h1"), Some(char_state()));
        // An update that reads holder in between does not forget the release.
        update(&mut m, relay_info("holder"), t0, 1_000);
        update(&mut m, relay_info("waiting"), t0, 14_000);
        assert_eq!(m.item_banner().unwrap().title, "BATON PASSED TO KAHLEEYA");
    }

    #[test]
    fn a_release_that_cannot_capture_in_time_is_dropped() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, None);
        release(&mut m, t0, 0, "h1");
        for at in (100..12_000).step_by(100) {
            assert!(captures(&go(&mut m, t0, at, None)).is_empty());
        }
        let fx = go(&mut m, t0, 12_000, None);
        assert!(captures(&fx).is_empty());
        assert_eq!(
            m.get_status(t0 + ms(12_000)),
            Some("Handoff cancelled: not in game")
        );
        let fx = go(&mut m, t0, 12_100, Some(IN_ZONE));
        assert!(captures(&fx).is_empty(), "{fx:?}");
        let fx = go(&mut m, t0, 12_200, Some(IN_ZONE));
        assert!(captures(&fx).is_empty());
    }

    #[test]
    fn an_unreadable_capture_is_asked_again_on_the_next_loaded_frame() {
        let (mut m, t0) = holder_with_capture_in_flight();
        // A loading screen swallowed the capture.
        go(&mut m, t0, 150, None);
        assert!(answer(&mut m, t0, 160, Some("h1"), None).is_empty());
        assert!(captures(&go(&mut m, t0, 200, None)).is_empty());
        let fx = go(&mut m, t0, 300, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
        let fx = answer(&mut m, t0, 350, Some("h1"), Some(char_state()));
        assert_eq!(sent_states(&fx).len(), 1);
    }

    #[test]
    fn an_answer_after_the_give_up_is_dropped() {
        let (mut m, t0) = holder_with_capture_in_flight();
        // In flight at the 12 s mark: the release is dropped, so is its answer.
        go_over(&mut m, t0, 200, 12_100, Some(IN_ZONE));
        let fx = answer(&mut m, t0, 12_200, Some("h1"), Some(char_state()));
        assert!(fx.is_empty());
        assert!(captures(&go(&mut m, t0, 12_300, Some(IN_ZONE))).is_empty());
        // An update flipping the runner shows no banner: nothing was answered.
        update(&mut m, relay_info("waiting"), t0, 12_400);
        assert!(m.item_banner().is_none());
        // The deadline passes between two frames: the answer is late all the same.
        let (mut m, t0) = holder_with_capture_in_flight();
        let fx = answer(&mut m, t0, 12_050, Some("h1"), Some(char_state()));
        assert!(fx.is_empty(), "{fx:?}");
    }

    #[test]
    fn a_release_is_ignored_unless_the_runner_holds_a_live_relay() {
        let t0 = Instant::now();
        let mut unknown = relay_info("holder");
        unknown.role = RelayRole::Unknown;
        let mut over = relay_info_with("holder", "finished");
        over.role = RelayRole::Holder;
        let cases = [
            ("waiting", relay_info("waiting")),
            ("unknown role", unknown),
            ("team over", over),
        ];
        for (name, info) in cases {
            let mut m = relay_machine("holder", t0);
            go(&mut m, t0, 0, Some(IN_ZONE));
            update(&mut m, info, t0, 10);
            release(&mut m, t0, 20, "h1");
            let fx = go_over(&mut m, t0, 100, 3_000, Some(IN_ZONE));
            assert!(
                !fx.iter()
                    .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })),
                "{name}"
            );
        }
        // No relay at all.
        let mut m = running_machine(t0);
        release(&mut m, t0, 20, "h1");
        let fx = go_over(&mut m, t0, 100, 1_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
    }

    #[test]
    fn a_holder_checkpoints_at_each_zone_reveal() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        let fx = go(&mut m, t0, 100, Some(IN_ZONE));
        assert_eq!(captures(&fx), [None]);
        go(&mut m, t0, 200, Some(IN_ZONE));
        let fx = answer(&mut m, t0, 250, None, Some(char_state()));
        assert_eq!(
            fx,
            [Effect::SendRelayState {
                handoff_id: None,
                state: char_state(),
                igt_ms: 5_000 + 200,
            }]
        );
        assert!(m.item_banner().is_none());
        // The next zone: another checkpoint.
        m.handle_message(zone_update("Liurnia", None), t0 + ms(300));
        let fx = go(&mut m, t0, 400, Some(IN_ZONE));
        assert_eq!(captures(&fx), [None]);
    }

    #[test]
    fn a_zone_reveal_outside_a_live_holder_asks_no_checkpoint() {
        let t0 = Instant::now();
        // A waiting runner, a team over, a role this build does not know.
        let mut unknown = relay_info("holder");
        unknown.role = RelayRole::Unknown;
        let mut over = relay_info_with("holder", "finished");
        over.role = RelayRole::Holder;
        for (name, info) in [
            ("waiting", relay_info("waiting")),
            ("over", over),
            ("unknown", unknown),
        ] {
            let mut m = relay_machine("holder", t0);
            go(&mut m, t0, 0, Some(IN_ZONE));
            update(&mut m, info, t0, 10);
            m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
            let fx = go_over(&mut m, t0, 100, 1_000, Some(IN_ZONE));
            assert!(
                !fx.iter()
                    .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })),
                "{name}"
            );
        }
        // A reveal while the socket is down is dropped, not sent after the
        // reconnection: the server only wants the latest.
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        let fx = frame(&mut m, t0, 100, Some(IN_ZONE), false);
        assert!(captures(&fx).is_empty());
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + ms(150),
        );
        let fx = go_over(&mut m, t0, 200, 1_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
    }

    #[test]
    fn a_reveal_during_a_capture_asks_no_second_one() {
        let (mut m, t0) = holder_with_capture_in_flight();
        m.handle_message(zone_update("Stormveil", None), t0 + ms(120));
        let fx = go(&mut m, t0, 200, Some(IN_ZONE));
        assert!(captures(&fx).is_empty());
        // The release's answer goes out under its own id; the reveal's
        // checkpoint was skipped, not queued.
        let fx = answer(&mut m, t0, 250, Some("h1"), Some(char_state()));
        assert_eq!(sent_states(&fx).len(), 1);
        let fx = go_over(&mut m, t0, 300, 2_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
    }

    #[test]
    fn a_checkpoint_capture_in_flight_makes_a_release_wait_for_its_answer() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        assert_eq!(captures(&go(&mut m, t0, 100, Some(IN_ZONE))), [None]);
        release(&mut m, t0, 150, "h1");
        assert!(captures(&go(&mut m, t0, 200, Some(IN_ZONE))).is_empty());
        // The checkpoint's answer goes out, then the release is asked.
        let fx = answer(&mut m, t0, 250, None, Some(char_state()));
        assert!(matches!(
            sent_states(&fx)[..],
            [Effect::SendRelayState {
                handoff_id: None,
                ..
            }]
        ));
        let fx = go(&mut m, t0, 300, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
    }

    #[test]
    fn a_release_at_a_zone_reveal_takes_the_one_capture() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        release(&mut m, t0, 60, "h1");
        let fx = go(&mut m, t0, 100, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
        let fx = go_over(&mut m, t0, 200, 1_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
        let fx = answer(&mut m, t0, 1_100, Some("h1"), Some(char_state()));
        assert_eq!(sent_states(&fx).len(), 1);
    }

    #[test]
    fn a_checkpoint_capture_that_fails_is_dropped() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        assert_eq!(captures(&go(&mut m, t0, 100, Some(IN_ZONE))), [None]);
        assert!(answer(&mut m, t0, 150, None, None).is_empty());
        let fx = go_over(&mut m, t0, 200, 2_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
    }

    #[test]
    fn a_second_release_replaces_the_first() {
        let (mut m, t0) = holder_with_capture_in_flight();
        release(&mut m, t0, 200, "h2");
        // The capture asked for h1 answers: nothing goes out under h1.
        assert!(answer(&mut m, t0, 250, Some("h1"), Some(char_state())).is_empty());
        let fx = go(&mut m, t0, 300, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h2".to_string())]);
        let fx = answer(&mut m, t0, 350, Some("h2"), Some(char_state()));
        assert!(matches!(
            sent_states(&fx)[..],
            [Effect::SendRelayState {
                handoff_id: Some(id),
                ..
            }] if id == "h2"
        ));
    }

    #[test]
    fn a_repeated_release_does_not_restart_its_clock() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, None);
        release(&mut m, t0, 0, "h1");
        release(&mut m, t0, 8_000, "h1");
        go(&mut m, t0, 12_000, None);
        assert_eq!(
            m.get_status(t0 + ms(12_000)),
            Some("Handoff cancelled: not in game")
        );
    }

    #[test]
    fn the_role_changing_while_a_capture_is_pending_drops_the_answer() {
        type Change = Box<dyn Fn(&mut RaceMachine, Instant)>;
        let changes: Vec<(&str, Change)> = vec![
            (
                "waiting",
                Box::new(|m, t0| update(m, relay_info("waiting"), t0, 120)),
            ),
            (
                "team over",
                Box::new(|m, t0| {
                    let mut info = relay_info_with("holder", "finished");
                    info.role = RelayRole::Holder;
                    update(m, info, t0, 120)
                }),
            ),
            (
                "runner out",
                Box::new(|m, t0| {
                    let mut info = relay_info("holder");
                    set_member_status(&mut info, "p1", ParticipantStatus::Abandoned);
                    update(m, info, t0, 120)
                }),
            ),
            (
                "race stopped",
                Box::new(|m, _t0| {
                    m.race_state.race.as_mut().unwrap().status = RaceStatus::Finished;
                }),
            ),
        ];
        for (name, change) in changes {
            let (mut m, t0) = holder_with_capture_in_flight();
            change(&mut m, t0);
            let fx = answer(&mut m, t0, 150, Some("h1"), Some(char_state()));
            assert!(fx.is_empty(), "{name}: {fx:?}");
            // And it is not asked again.
            let fx = go_over(&mut m, t0, 200, 2_000, Some(IN_ZONE));
            assert!(
                !fx.iter()
                    .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })),
                "{name}"
            );
        }
    }

    #[test]
    fn a_socket_drop_cancels_the_release_and_its_answer() {
        // Pending, not yet captured.
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, None);
        release(&mut m, t0, 50, "h1");
        frame(&mut m, t0, 100, None, false);
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + ms(200),
        );
        let fx = go_over(&mut m, t0, 300, 2_000, Some(IN_ZONE));
        assert!(
            !fx.iter()
                .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })),
            "the server cancelled it: no stale capture after the reconnection"
        );

        // In flight when the socket drops.
        let (mut m, t0) = holder_with_capture_in_flight();
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Reconnecting),
            t0 + ms(120),
        );
        m.handle_message(
            MachineMessage::StatusChanged(ConnectionStatus::Connected),
            t0 + ms(140),
        );
        let fx = answer(&mut m, t0, 160, Some("h1"), Some(char_state()));
        assert!(fx.is_empty(), "no stale answer: {fx:?}");
        let fx = go_over(&mut m, t0, 200, 2_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
    }

    #[test]
    fn a_checkpoint_in_flight_when_the_socket_drops_is_not_sent() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.handle_message(zone_update("Stormveil", None), t0 + ms(50));
        assert_eq!(captures(&go(&mut m, t0, 100, Some(IN_ZONE))), [None]);
        // The drop is seen by a frame, without a status message.
        frame(&mut m, t0, 150, Some(IN_ZONE), false);
        go(&mut m, t0, 200, Some(IN_ZONE));
        assert!(answer(&mut m, t0, 250, None, Some(char_state())).is_empty());
    }

    #[test]
    fn a_wrong_save_asks_no_capture() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        m.wrong_save = true;
        release(&mut m, t0, 50, "h1");
        let fx = go_over(&mut m, t0, 100, 1_000, Some(IN_ZONE));
        assert!(!fx
            .iter()
            .any(|(_, e)| matches!(e, Effect::CaptureRelayState { .. })));
        m.wrong_save = false;
        let fx = go(&mut m, t0, 1_100, Some(IN_ZONE));
        assert_eq!(captures(&fx), [Some("h1".to_string())]);
        // A save that went wrong during the capture: the answer is kept back.
        m.wrong_save = true;
        assert!(answer(&mut m, t0, 1_150, Some("h1"), Some(char_state())).is_empty());
    }

    #[test]
    fn an_answer_nobody_asked_for_sends_nothing() {
        let t0 = Instant::now();
        let mut m = relay_machine("holder", t0);
        go(&mut m, t0, 0, Some(IN_ZONE));
        assert!(answer(&mut m, t0, 50, None, Some(char_state())).is_empty());
        assert!(answer(&mut m, t0, 60, Some("h1"), Some(char_state())).is_empty());
    }

    #[test]
    fn an_oversized_state_is_cut_to_the_wire_caps() {
        let (mut m, t0) = holder_with_capture_in_flight();
        let mut big = char_state();
        big.items = (0..4_005).map(|i| 0x4000_0000 + i).rev().collect();
        big.grace_flags = vec![2_147_483_648, 71800, 71800];
        let fx = answer(&mut m, t0, 150, Some("h1"), Some(big));
        let [Effect::SendRelayState { state, .. }] = &fx[..] else {
            panic!("{fx:?}");
        };
        assert_eq!(state.items.len(), 4_000);
        assert_eq!(state.items[0], 0x4000_0000);
        assert_eq!(state.grace_flags, [71800]);
    }
}
