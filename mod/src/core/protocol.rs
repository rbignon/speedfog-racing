//! WebSocket protocol types for SpeedFog Racing
//!
//! Messages exchanged between the mod and the racing server.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Wire-protocol version, independent from the crate release version.
/// Bump rules: breaking change -> major + 1 (minor resets to 0);
/// backward-compatible addition worth signalling -> minor + 1; otherwise
/// unchanged. Keep in sync with PROTOCOL_VERSION in
/// server/speedfog_racing/websocket/schemas.py and docs/PROTOCOL.md.
pub const PROTOCOL_VERSION: &str = "1.19";

// =============================================================================
// CLIENT -> SERVER MESSAGES
// =============================================================================

/// Messages sent from mod to server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Authentication with mod token
    Auth {
        mod_token: String,
        /// Wire-protocol version spoken by this build ("major.minor").
        protocol_version: String,
        /// Crate release version, for server logs and admin display only.
        mod_version: String,
    },
    /// Player is ready to race
    Ready,
    /// Periodic status update.
    ///
    /// `weapons` is `[left_hand, right_hand]` raw EquipParamWeapon runtime IDs
    /// (row + upgrade level). Per slot, `None` means empty hand, two-handed mask,
    /// loading screen, or unreadable memory.
    ///
    /// `debug_flags` lists the wire names (`core::debug_flags`) of the game
    /// debug flags seen since the race start; omitted when empty.
    StatusUpdate {
        igt_ms: u32,
        death_count: u32,
        weapons: [Option<i32>; 2],
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        debug_flags: Vec<String>,
    },
    /// EMEVD event flag triggered (fog gate traversal or boss kill)
    EventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    /// Zone query at loading screen exit (server resolves to graph node)
    ZoneQuery {
        igt_ms: u32,
        message_id: u64,
        #[serde(skip_serializing_if = "Option::is_none")]
        grace_entity_id: Option<u32>,
        #[serde(skip_serializing_if = "Option::is_none")]
        map_id: Option<String>,
        #[serde(skip_serializing_if = "Option::is_none")]
        position: Option<[f32; 3]>,
        #[serde(skip_serializing_if = "Option::is_none")]
        play_region_id: Option<u32>,
        /// True when this query follows a detected quit-out (reload in
        /// place): the server resumes the current zone instead of guessing.
        #[serde(default, skip_serializing_if = "is_false")]
        quit_out: bool,
    },
    /// A race item grant was received (spawn handled); lets the server stop
    /// replaying it.
    ItemReceived { grant_id: u64 },
    /// Catalog goods keys of the race goods currently held (quantity above 0).
    ItemInventory { goods: Vec<String> },
    /// The outcome of a `steal_talisman` or `hunter` effect (1.17): whether
    /// a talisman was taken or the Hunter spawned. `talisman_id` is the
    /// talisman taken, sent null otherwise.
    ItemReport {
        report_id: u64,
        landed: bool,
        talisman_id: Option<u32>,
    },
    /// Relay (1.19): a waiting runner is (or stops being) loaded at the
    /// Chapel with its lock raised.
    RelayReady { ready: bool },
    /// Relay (1.19): the holder confirmed a teammate in the menu.
    RelayHandoffRequest { to_participant_id: String },
    /// Relay (1.19): a waiting runner asks for a free baton.
    RelayTakeRequest,
    /// Relay (1.19): a checkpoint (`handoff_id` null, always serialized) or
    /// the answer to a `relay_release`.
    RelayState {
        handoff_id: Option<String>,
        state: CharacterState,
        igt_ms: u32,
    },
    /// Relay (1.19): the new holder applied the take and raised its warp flag.
    RelayTaken { handoff_id: String },
    /// Relay (1.19): the member's save was validated with this token.
    RelayBound { token: u32 },
    /// Heartbeat response
    Pong,
}

// =============================================================================
// SERVER -> CLIENT MESSAGES
// =============================================================================

/// Machine-readable condition codes on the server `error` message.
/// Same additive convention as [`RaceStatus`]: a code this build doesn't
/// know deserializes as `Unknown` instead of failing, and is treated as
/// "no known condition" (legacy transient display) by the machine.
///
/// `WrongSave` is the server's own detection, independent of the mod's
/// local IGT-derived freeze heuristic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConditionKind {
    WrongSave,
    FreshSaveRequired,
    RaceNotRunning,
    Countdown,
    SessionInactive,
    #[serde(other)]
    Unknown,
}

impl ConditionKind {
    /// Display category: blocking conditions take the red top banner,
    /// the rest the amber waiting line.
    pub fn is_blocking(&self) -> bool {
        matches!(self, Self::WrongSave | Self::FreshSaveRequired)
    }
}

/// Visual customization payload for the participant's username on the in-game
/// leaderboard. Only color/gradient is delivered to the mod; backgrounds are
/// web-only.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NameTemplate {
    #[serde(default)]
    pub color: Option<String>,
    #[serde(default)]
    pub gradient: Option<(String, String)>,
}

/// Race lifecycle status. Wire format: lowercase strings, identical to the
/// previous stringly-typed field. `Unknown` preserves the additive protocol
/// convention: a status this build doesn't know deserializes instead of
/// failing, and is treated as "no known state matches" everywhere.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RaceStatus {
    Setup,
    Running,
    Finished,
    #[serde(other)]
    Unknown,
}

impl RaceStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            RaceStatus::Setup => "setup",
            RaceStatus::Running => "running",
            RaceStatus::Finished => "finished",
            RaceStatus::Unknown => "unknown",
        }
    }
}

/// Participant lifecycle status. Same wire/forward-compat contract as
/// [`RaceStatus`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ParticipantStatus {
    Registered,
    Ready,
    Playing,
    Finished,
    Abandoned,
    Disqualified,
    #[serde(other)]
    Unknown,
}

impl ParticipantStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            ParticipantStatus::Registered => "registered",
            ParticipantStatus::Ready => "ready",
            ParticipantStatus::Playing => "playing",
            ParticipantStatus::Finished => "finished",
            ParticipantStatus::Abandoned => "abandoned",
            ParticipantStatus::Disqualified => "disqualified",
            ParticipantStatus::Unknown => "unknown",
        }
    }

    /// Out of the race without a finish: abandoned or disqualified. Both
    /// freeze the runner's IGT on the server and end their race.
    pub fn is_out(&self) -> bool {
        matches!(
            self,
            ParticipantStatus::Abandoned | ParticipantStatus::Disqualified
        )
    }
}

/// Reads a layer -> IGT map. JSON object keys are strings, and once an
/// internally tagged enum (`ServerMessage`) has buffered them serde can no
/// longer read them as integers, so they are read as strings and parsed
/// (`parse_splits`: a key that is not an integer is dropped).
fn deserialize_layer_map<'de, D>(deserializer: D) -> Result<Option<HashMap<i32, i32>>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Ok(Option::<HashMap<String, i32>>::deserialize(deserializer)?.map(crate::core::parse_splits))
}

/// Reads an event flag -> layer map sent with String keys (see
/// `deserialize_layer_map`). A key that is not a u32 is dropped.
fn deserialize_flag_layers<'de, D>(deserializer: D) -> Result<HashMap<u32, i32>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    Ok(Option::<HashMap<String, i32>>::deserialize(deserializer)?
        .unwrap_or_default()
        .into_iter()
        .filter_map(|(k, v)| k.parse::<u32>().ok().map(|k| (k, v)))
        .collect())
}

/// Participant info in leaderboard
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ParticipantInfo {
    pub id: String,
    pub twitch_username: String,
    pub twitch_display_name: Option<String>,
    pub status: ParticipantStatus,
    pub current_zone: Option<String>,
    pub current_layer: i32,
    #[serde(default)]
    pub current_layer_tier: Option<i32>,
    pub igt_ms: i32,
    pub death_count: i32,
    #[serde(default)]
    pub gap_ms: Option<i32>,
    #[serde(default)]
    pub layer_entry_igt: Option<i32>,
    /// IGT of the first arrival on each layer reached (the finish counting as
    /// layer `total_layers`): the splits a gap to this runner is measured
    /// against. Absent from servers speaking protocol < 1.7, null where the
    /// server does not send it (e.g. on `auth_ok`).
    #[serde(default, deserialize_with = "deserialize_layer_map")]
    pub layer_entry_igts: Option<HashMap<i32, i32>>,
    #[serde(default)]
    pub name_template: Option<NameTemplate>,
}

/// Race info from server.
///
/// Carries every race-level field the server may push at any time. Only the
/// fields the mod actually uses are read by the UI today (status, race_ends_at,
/// igt_cutoff_ms, countdown_seconds); the rest are kept on the struct so a
/// single payload shape covers `auth_ok`, `race_state` and `race_info_update`
/// and so the protocol stays symmetrical with the spectator client.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RaceInfo {
    pub id: String,
    pub name: String,
    pub status: RaceStatus,
    #[serde(default)]
    pub is_public: bool,
    #[serde(default)]
    pub open_registration: bool,
    #[serde(default)]
    pub max_participants: Option<i32>,
    #[serde(default)]
    pub scheduled_at: Option<String>,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub seeds_released_at: Option<String>,
    #[serde(default)]
    pub registration_closes_at: Option<String>,
    #[serde(default)]
    pub race_ends_at: Option<String>,
    /// In-game time (ms) a run must finish by: past it the server eliminates
    /// a playing runner, and the overlay counts the local IGT down to it.
    /// Absent from servers older than protocol 1.8, null on a race without one.
    #[serde(default)]
    pub igt_cutoff_ms: Option<u32>,
    #[serde(default)]
    pub private_dag: bool,
    /// Deathless race: the server abandons a participant on their first
    /// in-race death. The mod shows a local death banner and an overlay tag.
    #[serde(default)]
    pub deathless: bool,
    /// Race items enabled: the mod reads item use flags and handles item
    /// messages. Absent from servers older than protocol 1.12.
    #[serde(default)]
    pub race_items: bool,
    /// Ranked run (Speedrun or Set Seed mode). A solo session reads debug
    /// flags only when ranked. Absent from servers older than protocol 1.9.
    #[serde(default)]
    pub ranked: bool,
    #[serde(default)]
    pub countdown_seconds: u32,
    /// Current seed id of the race. Lets the mod detect that its loaded seed
    /// pack went stale (e.g. after a reroll) outside the `auth_ok` handshake,
    /// by comparing it against the configured pack's seed id.
    #[serde(default)]
    pub seed_id: Option<String>,
    /// IGT penalty (ms) the mod applies per detected quit-out; 0 disables.
    /// Defaults so a server predating the field keeps the feature active.
    #[serde(default = "default_quit_out_penalty_ms")]
    pub quit_out_penalty_ms: u32,
    /// Opaque id of the run's current attempt: changes when a race is reset
    /// and run again or its seed re-rolled after the start, or a Set Seed
    /// solo run is reset. None before a race
    /// starts (the start's `race_info_update` brings it) and from older
    /// servers.
    #[serde(default)]
    pub attempt_id: Option<String>,
    /// Pre-parsed `race_ends_at` filled by [`RaceInfo::reparse_dates`] after
    /// receipt so the per-frame countdown UI doesn't reparse the string.
    /// Not part of the wire format.
    ///
    /// Call sites that store a freshly deserialized `RaceInfo` MUST call
    /// [`RaceInfo::reparse_dates`] first; otherwise this stays `None` and the
    /// countdown silently doesn't render. Also note that this field
    /// participates in the derived `PartialEq`, so two structurally identical
    /// payloads compare unequal if only one has been reparsed.
    #[serde(skip)]
    pub race_ends_at_dt: Option<DateTime<Utc>>,
}

impl RaceInfo {
    /// Populate non-serde cached fields from their RFC3339 string counterparts.
    /// Call after deserializing or replacing a `RaceInfo` so render code can
    /// read the parsed `DateTime` directly.
    pub fn reparse_dates(&mut self) {
        self.race_ends_at_dt = self
            .race_ends_at
            .as_deref()
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .map(|dt| dt.with_timezone(&Utc));
    }
}

/// Item to be spawned at runtime by the mod (e.g., Gem/Ash of War).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SpawnItem {
    pub id: u32,
    #[serde(default = "default_qty")]
    pub qty: u32,
}

fn default_qty() -> u32 {
    1
}

fn is_false(v: &bool) -> bool {
    !*v
}

fn default_quit_out_penalty_ms() -> u32 {
    2000
}

/// Mod-side directives for a phantom skin.
///
/// V1 ships only `speffects`. New keys (e.g. `fxr_ids`) added in future
/// versions are no-ops on older mods, and missing keys default to empty so
/// older seeds without those keys stay compatible.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct PhantomSkin {
    #[serde(default)]
    pub speffects: Vec<i32>,
}

/// Seed info from server
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SeedInfo {
    pub total_layers: i32,
    #[serde(default)]
    pub event_ids: Vec<u32>,
    /// Flag ID for the final boss kill, sent immediately (no loading screen).
    #[serde(default)]
    pub finish_event: Option<u32>,
    #[serde(default)]
    pub spawn_items: Vec<SpawnItem>,
    /// Seed ID, compared against config to detect stale seed packs after re-roll
    #[serde(default)]
    pub seed_id: Option<String>,
    /// Death marker event flags per cluster: [flag_low, flag_med, flag_high]
    #[serde(default)]
    pub death_flags: HashMap<String, [u32; 3]>,
    /// Event flag for persistent re-spawn prevention (saved range).
    /// When None (old server), only in-process guard prevents double-spawn.
    #[serde(default)]
    pub items_spawned_flag: Option<u32>,
    /// Per-seed map of skin name -> directives. The mod looks up the equipped
    /// skin name (received in auth_ok.phantom_skin) here to resolve it to
    /// concrete SpEffect IDs etc.
    #[serde(default)]
    pub phantom_skins: HashMap<String, PhantomSkin>,
    /// Event flag -> layer for the LiveSplit driver: the layer a flag arrival
    /// means. Empty from an old server, which disables LiveSplit driving.
    #[serde(default, deserialize_with = "deserialize_flag_layers")]
    pub flag_layers: HashMap<u32, i32>,
    /// Seed number, matched against the LiveSplit seed custom variable.
    #[serde(default)]
    pub seed_number: Option<String>,
    /// Race category, matched against the LiveSplit category custom variable.
    #[serde(default)]
    pub category: Option<String>,
    /// Boss defeat flags of every boss node but the final boss (whose kill
    /// is the finish): each is reported once through event_flag and never
    /// cleared in game memory. Empty from an old server.
    #[serde(default)]
    pub boss_flags: Vec<u32>,
    /// Race item catalog: the race goods and the items they hold. Empty
    /// from an old server or a race without items.
    #[serde(default)]
    pub race_item_catalog: RaceItemCatalog,
}

/// A seed's race item catalog: goods and items, each by key. Every usable
/// item is held as one shared goods; an item without a use has its own.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct RaceItemCatalog {
    #[serde(default)]
    pub goods: HashMap<String, RaceItemGoods>,
    #[serde(default)]
    pub items: HashMap<String, RaceItemEntry>,
}

/// One race goods: its goods id, the flag the game raises when the player
/// uses it (None for a goods without a use action), the flag the mod raises
/// to make the game remove it, and the icon id its param row starts with.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RaceItemGoods {
    pub goods_id: u32,
    #[serde(default)]
    pub use_flag: Option<u32>,
    pub remove_flag: u32,
    pub icon_id: u16,
}

/// One race item: its display name and overlay icon (the held row), the
/// in-game icon id written into its goods' param row while it is held, and
/// the key of the goods it is held as.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RaceItemEntry {
    pub name: String,
    pub icon: String,
    pub icon_id: u16,
    pub goods: String,
}

/// Banner text of a race item event.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemBanner {
    pub icon: String,
    pub title: String,
    pub line: String,
    pub detail: String,
}

/// Timed reminder row shown in the race panel.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ItemReminder {
    pub text: String,
    pub duration_ms: u32,
}

/// What a race item effect does to the local player.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ItemEffectPayload {
    /// Apply a game SpEffect. `duration_ms` is set for a timed effect
    /// (1.14), absent for an instant one and from older servers.
    Speffect {
        speffect_id: u32,
        #[serde(default)]
        duration_ms: Option<u32>,
    },
    /// Damage by percent of max HP, following the floor/tail curve.
    Damage {
        base_pct: u8,
        floor_pct: u8,
        tail_pct: u8,
    },
    /// Hide exit destinations for a duration.
    Ink { duration_ms: u32 },
    /// Apply a SpEffect whose max equip load rate is first set so the
    /// player's current load sits at `load_pct` percent of the max, for
    /// `duration_ms` (1.14; absent from older servers).
    EquipLoad {
        speffect_id: u32,
        load_pct: u8,
        #[serde(default)]
        duration_ms: Option<u32>,
    },
    /// The player turns invisible for `duration_ms` (1.15).
    Vanish { duration_ms: u32 },
    /// The enemies around the player are hidden for `duration_ms` (1.15).
    UnseenFoes { duration_ms: u32 },
    /// The player's animations run at `speed_pct` percent of their speed
    /// for `duration_ms` (1.15).
    SlowMo { speed_pct: u16, duration_ms: u32 },
    /// The player is scaled to `scale_pct` percent of their size for
    /// `duration_ms` (1.15; the Giant).
    Scale { scale_pct: u16, duration_ms: u32 },
    /// The Lightning: apply the SpEffect `speffect_id` (a forced slow walk)
    /// and scale the player to `scale_pct` percent of their size, both for
    /// `duration_ms` (1.18).
    Lightning {
        speffect_id: u32,
        scale_pct: u16,
        duration_ms: u32,
    },
    /// The camera turns to `variant` for `duration_ms` (1.15).
    Camera {
        variant: CameraVariant,
        duration_ms: u32,
    },
    /// The Talisman Thief takes one of the talismans the player wears
    /// (1.17): `talismans` is the seed's table, `roll` picks among those
    /// worn (`core::talisman_thief`). Answered with an `item_report`.
    StealTalisman {
        talismans: Vec<TalismanFlag>,
        roll: u32,
        report_id: u64,
    },
    /// The thief's gift, once the victim reported the talisman taken (1.17).
    Talisman { talisman_id: u32 },
    /// A junk weapon forced into the player's right hand (1.17).
    JunkWeapon { weapon_id: u32 },
    /// The Hunter: the character `chr_id` spawned with the NpcParam row
    /// `npc_param_id` (its tier's) and the NpcThinkParam row `think_id`,
    /// hunting the player for `duration_ms` once found (1.17). Answered
    /// with an `item_report`.
    Hunter {
        chr_id: u32,
        npc_param_id: u32,
        think_id: u32,
        duration_ms: u32,
        report_id: u64,
    },
    /// A kind this build does not know: ignored with a warning.
    #[serde(other)]
    Unknown,
}

/// One talisman of the seed's table: its EquipParamAccessory id and the
/// event flag whose removal event takes it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct TalismanFlag {
    pub id: u32,
    pub flag: u32,
}

/// The Camera item's variant, drawn by the server at each use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CameraVariant {
    FirstPerson,
    Inverted,
    Wide,
    /// A variant this build does not know: the effect is dropped with a
    /// warning.
    #[serde(other)]
    Unknown,
}

/// What a relay handoff carries: the event flags of the lit graces, nothing
/// of the character (each runner keeps their own). A state with other fields
/// reads as its graces, the rest ignored. The wire caps a grace flag at
/// 2^31 - 1 and a state at 1000 of them.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CharacterState {
    pub grace_flags: Vec<u32>,
}

/// A runner's role in its relay team. Additive like [`RaceStatus`]: a role
/// this build does not know deserializes as `Unknown`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RelayRole {
    Holder,
    Waiting,
    #[serde(other)]
    Unknown,
}

/// One member of a relay team. `ready` and `validated` default to false: a
/// member whose readiness is unknown is never proposed as a handoff target.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelayMember {
    pub participant_id: String,
    pub name: String,
    pub zones: u32,
    pub status: ParticipantStatus,
    pub online: bool,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub validated: bool,
}

/// The seed's relay event flags (the server sends them, never constants).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelayFlags {
    pub lock_flag: u32,
    pub chapel_warp_flag: u32,
    pub warp_flag_base: u32,
    pub zone_flag_base: u32,
    pub travel_lock_flag: u32,
    pub roundtable_warp_flag: u32,
    pub token_flag_base: u32,
    pub token_bits: u32,
}

/// What the mod is told about its relay team and its own role. `team_status`
/// is the team's [`ParticipantStatus`]; `baton_free_in_s` is null while the
/// holder is online, otherwise the seconds before the baton can be taken.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelayInfo {
    pub team_id: String,
    pub team_name: String,
    pub team_status: ParticipantStatus,
    pub cap: u32,
    pub holder_id: Option<String>,
    pub holder_online: bool,
    #[serde(default)]
    pub zone_name: Option<String>,
    pub baton_free_in_s: Option<u32>,
    pub role: RelayRole,
    pub gates_locked: bool,
    pub members: Vec<RelayMember>,
    pub flags: RelayFlags,
    /// The member's save token, null until their save is validated.
    #[serde(default)]
    pub token: Option<u32>,
    /// Whether the member is bound to the character of their token.
    #[serde(default)]
    pub bound: bool,
}

/// One item of a relay loot entry.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelayLootItem {
    pub id: u32,
    pub qty: u32,
}

/// The loot of one boss the team killed.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelayLootEntry {
    pub flag: u32,
    pub received_flag: u32,
    pub pickup_flags: Vec<u32>,
    pub items: Vec<RelayLootItem>,
    pub rune_speffect: Option<u32>,
    pub runes: u32,
}

/// Who defeated which boss, for the banner of a live loot.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RelayLootAnnounce {
    pub runner: String,
    pub boss: String,
}

/// Exit info in zone_update message
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExitInfo {
    pub text: String,
    pub to_name: String,
    pub discovered: bool,
}

/// Messages received from server
#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Authentication successful
    AuthOk {
        participant_id: String,
        // Boxed to keep `ServerMessage` small: `RaceInfo` dwarfs every other
        // variant, so an inline copy would bloat all of them (large_enum_variant).
        race: Box<RaceInfo>,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
        #[serde(default)]
        phantom_skin: Option<String>,
        /// Server release version, present only when a newer compatible mod
        /// build exists (protocol minor ahead). Absent from old servers.
        #[serde(default)]
        latest_mod_version: Option<String>,
        /// Race item key the runner holds, confirmed or not (None when
        /// nothing is held, without items, or from an old server).
        #[serde(default)]
        held_item: Option<String>,
        /// The runner's relay team (1.19); absent or null on any other race.
        #[serde(default)]
        relay: Option<Box<RelayInfo>>,
    },
    /// Authentication failed
    AuthError { message: String },
    /// Race has started (with optional countdown)
    RaceStart {
        #[serde(default)]
        countdown_seconds: u32,
    },
    /// Leaderboard update
    LeaderboardUpdate {
        participants: Vec<ParticipantInfo>,
        #[serde(default)]
        leader_splits: Option<HashMap<String, i32>>,
    },
    /// Race status changed
    RaceStatusChange { status: RaceStatus },
    /// Race-level info changed (race_ends_at extension, etc.) and the cached
    /// RaceInfo on the client must be replaced wholesale with this snapshot.
    RaceInfoUpdate { race: Box<RaceInfo> },
    /// Single player update
    PlayerUpdate { player: ParticipantInfo },
    /// Zone update (unicast to originating mod)
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        #[serde(default)]
        original_tier: Option<i32>,
        #[serde(default)]
        layer: Option<i32>,
        #[serde(default)]
        is_first_visit: bool,
        #[serde(default)]
        exits: Vec<ExitInfo>,
        /// Exits of the zone no edge takes; `None` on a seed older than
        /// graph.json 4.13.
        #[serde(default)]
        unused_exits: Option<u32>,
        /// The zone's boss defeat flag (a boss arena, the final boss aside),
        /// one of the seed's `boss_flags`; `None` elsewhere.
        #[serde(default)]
        defeat_flag: Option<u32>,
        #[serde(default)]
        message_id: Option<u64>,
    },
    /// Acknowledges persistence of an event_flag message.
    EventFlagAck { message_id: u64 },
    /// Acknowledges a zone_query that could not produce a zone_update
    /// (unresolved, wrong state, etc.) so the mod can clear in-flight tracking.
    ZoneQueryAck { message_id: u64 },
    /// Aggregated death counts per zone (for conditional death markers)
    DeathCounts { counts: HashMap<String, u32> },
    /// Heartbeat ping
    Ping,
    /// Generic error from server (e.g., race not running). `code` is the
    /// machine-readable condition tag (None on plain errors and old servers;
    /// codes this build doesn't know deserialize as `Unknown`).
    Error {
        message: String,
        #[serde(default)]
        code: Option<ConditionKind>,
    },
    /// Daily-streak update, unicast by the server to a user's connections
    /// after a daily run. The in-game mod has no use for it; it is modeled
    /// here only so the message deserializes cleanly and is dropped by the
    /// catch-all match arm, instead of tripping the parse-failure warning.
    /// The payload (current/best/freeze_count/...) is intentionally ignored.
    DailyStreakUpdate {},
    /// A race item was granted to the local player.
    ItemGrant {
        grant_id: u64,
        item: String,
        banner: ItemBanner,
    },
    /// A race item effect hits the local player. Without a banner for the
    /// player's own self item, whose `item_result` carries it.
    ItemEffect {
        item: String,
        effect: ItemEffectPayload,
        #[serde(default)]
        banner: Option<ItemBanner>,
        #[serde(default)]
        reminder: Option<ItemReminder>,
    },
    /// Outcome shown to the player who used an item.
    ItemResult {
        item: String,
        banner: ItemBanner,
        #[serde(default)]
        reminder: Option<ItemReminder>,
    },
    /// Remove a held race goods (a spent Shield, a take-back), with an
    /// optional banner.
    ItemRemove {
        goods: String,
        #[serde(default)]
        banner: Option<ItemBanner>,
    },
    /// A banner with nothing applied (1.15): a Star holder's block.
    ItemNotice { banner: ItemBanner },
    /// Relay (1.19): the team's `RelayInfo` changed; replaces the cached one.
    RelayUpdate { relay: Box<RelayInfo> },
    /// Relay (1.19), to the holder: send your state, lock, go to the Chapel.
    RelayRelease { handoff_id: String, to_name: String },
    /// Relay (1.19), to the new holder: the state to apply. `state` is null
    /// when none is known yet; `warp_flag` is null before the team's first gate.
    RelayTake {
        handoff_id: String,
        state: Option<CharacterState>,
        igt_ms: u32,
        #[serde(default)]
        defeat_flags: Vec<u32>,
        warp_flag: Option<u32>,
        zone_name: Option<String>,
    },
    /// Relay (1.19): a request was refused. The mod shows `message` and logs
    /// `code`; it branches on no code.
    RelayRefused { code: String, message: String },
    /// Relay (1.19): the loot of the team's bosses. `announce` is null for a
    /// catch-up list, `paid` tells whether the member was already paid.
    RelayLoot {
        entries: Vec<RelayLootEntry>,
        paid: bool,
        announce: Option<RelayLootAnnounce>,
    },
}

// =============================================================================
// HELPERS
// =============================================================================

/// Returns true if the WebSocket close code represents a permanent error
/// that should not trigger reconnection (application-level rejection).
pub fn is_permanent_close(code: u16) -> bool {
    code >= 4000
}

// =============================================================================
// TESTS
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_auth_serialize() {
        let msg = ClientMessage::Auth {
            mod_token: "test123".to_string(),
            protocol_version: PROTOCOL_VERSION.to_string(),
            mod_version: env!("CARGO_PKG_VERSION").to_string(),
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"auth""#));
        assert!(json.contains(r#""mod_token":"test123""#));
        assert!(json.contains(&format!(r#""protocol_version":"{}""#, PROTOCOL_VERSION)));
        assert!(json.contains(&format!(r#""mod_version":"{}""#, env!("CARGO_PKG_VERSION"))));
    }

    #[test]
    fn test_client_status_update_serialize() {
        let msg = ClientMessage::StatusUpdate {
            igt_ms: 123456,
            death_count: 5,
            weapons: [Some(2000025), None],
            debug_flags: vec![],
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"status_update""#));
        assert!(json.contains(r#""igt_ms":123456"#));
        assert!(json.contains(r#""death_count":5"#));
        assert!(json.contains(r#""weapons":[2000025,null]"#));
        // Should NOT contain current_zone or current_layer
        assert!(!json.contains("current_zone"));
        assert!(!json.contains("current_layer"));
    }

    #[test]
    fn test_client_event_flag_serialize() {
        let msg = ClientMessage::EventFlag {
            flag_id: 9000042,
            igt_ms: 60000,
            message_id: 42,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"event_flag""#));
        assert!(json.contains(r#""flag_id":9000042"#));
        assert!(json.contains(r#""igt_ms":60000"#));
        assert!(json.contains(r#""message_id":42"#));
    }

    #[test]
    fn test_server_event_flag_ack_deserialize() {
        let json = r#"{"type":"event_flag_ack","message_id":99}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::EventFlagAck { message_id } => assert_eq!(message_id, 99),
            _ => panic!("Expected EventFlagAck"),
        }
    }

    #[test]
    fn test_server_auth_ok_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk {
                participant_id,
                race,
                seed,
                ..
            } => {
                assert_eq!(participant_id, "abc-123");
                assert_eq!(race.name, "Test Race");
                assert_eq!(seed.total_layers, 5);
                // event_ids defaults to empty vec when absent
                assert!(seed.event_ids.is_empty());
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_auth_ok_latest_mod_version() {
        // New server pushing an update notice.
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "latest_mod_version": "1.18.0"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk {
                latest_mod_version, ..
            } => assert_eq!(latest_mod_version.as_deref(), Some("1.18.0")),
            _ => panic!("Expected AuthOk"),
        }

        // Old server: field absent, defaults to None.
        let json_old = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json_old).unwrap();
        match msg {
            ServerMessage::AuthOk {
                latest_mod_version, ..
            } => assert!(latest_mod_version.is_none()),
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_auth_ok_with_event_ids_deserialize() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "def-456",
            "race": {"id": "456", "name": "Flag Race", "status": "running"},
            "seed": {"total_layers": 3, "event_ids": [9000001, 9000042, 9000100]},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.event_ids, vec![9000001, 9000042, 9000100]);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_livesplit_fields_inside_a_server_message() {
        let json = r#"{"type": "auth_ok", "participant_id": "p", "race": {"id": "r", "name": "R", "status": "running"},
            "seed": {"total_layers": 3, "flag_layers": {"100": 1, "200": 2, "x": 9},
                     "seed_number": "abc123", "category": "standard@25"},
            "participants": [{"id": "p", "twitch_username": "u", "status": "playing", "current_layer": 1,
                              "igt_ms": 0, "death_count": 0, "layer_entry_igts": {"0": 0, "1": 5000}}]}"#;
        match serde_json::from_str::<ServerMessage>(json).unwrap() {
            ServerMessage::AuthOk {
                seed, participants, ..
            } => {
                assert_eq!(seed.flag_layers, HashMap::from([(100, 1), (200, 2)]));
                assert_eq!(seed.seed_number.as_deref(), Some("abc123"));
                assert_eq!(seed.category.as_deref(), Some("standard@25"));
                assert_eq!(
                    participants[0].layer_entry_igts,
                    Some(HashMap::from([(0, 0), (1, 5000)]))
                );
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_without_livesplit_fields_from_old_server() {
        let json = r#"{"type": "auth_ok", "participant_id": "p",
            "race": {"id": "r", "name": "R", "status": "running"},
            "seed": {"total_layers": 3}, "participants": []}"#;
        match serde_json::from_str::<ServerMessage>(json).unwrap() {
            ServerMessage::AuthOk { seed, .. } => {
                assert!(seed.flag_layers.is_empty());
                assert!(seed.seed_number.is_none());
                assert!(seed.category.is_none());
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_seed_info_without_event_ids() {
        // Backward compat: old server sends no event_ids field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.total_layers, 5);
        assert!(seed.event_ids.is_empty());
    }

    #[test]
    fn test_server_race_start_deserialize() {
        // Backward compat: no countdown_seconds field → defaults to 0
        let json = r#"{"type": "race_start"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceStart { countdown_seconds } => {
                assert_eq!(countdown_seconds, 0);
            }
            _ => panic!("Expected RaceStart"),
        }
    }

    #[test]
    fn test_server_race_start_with_countdown() {
        let json = r#"{"type": "race_start", "countdown_seconds": 10}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceStart { countdown_seconds } => {
                assert_eq!(countdown_seconds, 10);
            }
            _ => panic!("Expected RaceStart"),
        }
    }

    #[test]
    fn test_server_leaderboard_update_deserialize() {
        let json = r#"{
            "type": "leaderboard_update",
            "participants": [{
                "id": "1",
                "twitch_username": "player1",
                "twitch_display_name": "Player One",
                "status": "playing",
                "current_zone": "Limgrave",
                "current_layer": 2,
                "current_layer_tier": 3,
                "igt_ms": 60000,
                "death_count": 1
            }]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                assert_eq!(participants.len(), 1);
                assert_eq!(participants[0].twitch_username, "player1");
                assert_eq!(participants[0].current_layer_tier, Some(3));
                assert_eq!(leader_splits, None);
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_server_ping_deserialize() {
        let json = r#"{"type": "ping"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        assert!(matches!(msg, ServerMessage::Ping));
    }

    #[test]
    fn test_client_pong_serialize() {
        let msg = ClientMessage::Pong;
        let json = serde_json::to_string(&msg).unwrap();
        assert_eq!(json, r#"{"type":"pong"}"#);
    }

    #[test]
    fn test_server_zone_update_deserialize() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "graveyard_cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": [
                { "text": "Soldier of Godrick front", "to_name": "Road's End Catacombs", "discovered": false },
                { "text": "Stranded Graveyard first door", "to_name": "Ruin-Strewn Precipice", "discovered": true }
            ]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
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
                assert_eq!(node_id, "graveyard_cave_e235");
                assert_eq!(display_name, "Cave of Knowledge");
                assert_eq!(tier, Some(5));
                assert_eq!(original_tier, None);
                assert_eq!(layer, None);
                assert!(!is_first_visit);
                assert_eq!(exits.len(), 2);
                assert_eq!(exits[0].text, "Soldier of Godrick front");
                assert_eq!(exits[0].to_name, "Road's End Catacombs");
                assert!(!exits[0].discovered);
                assert!(exits[1].discovered);
                assert_eq!(message_id, None);
                // A seed older than graph.json 4.13 sends no count, and a
                // server older than 1.16 no defeat flag.
                assert_eq!(unused_exits, None);
                assert_eq!(defeat_flag, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_unused_exits() {
        let json =
            r#"{"type":"zone_update","node_id":"n","display_name":"N","tier":1,"unused_exits":2}"#;
        match serde_json::from_str::<ServerMessage>(json).unwrap() {
            ServerMessage::ZoneUpdate { unused_exits, .. } => assert_eq!(unused_exits, Some(2)),
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_defeat_flag() {
        let json = r#"{"type":"zone_update","node_id":"n","display_name":"N","tier":1,"defeat_flag":10000800}"#;
        match serde_json::from_str::<ServerMessage>(json).unwrap() {
            ServerMessage::ZoneUpdate { defeat_flag, .. } => {
                assert_eq!(defeat_flag, Some(10_000_800))
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_first_visit() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_node",
            "display_name": "Some Cave",
            "tier": 3,
            "is_first_visit": true,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                is_first_visit,
                exits,
                ..
            } => {
                assert!(is_first_visit);
                assert!(exits.is_empty());
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_no_tier() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "start_node",
            "display_name": "Chapel of Anticipation",
            "tier": null,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { tier, exits, .. } => {
                assert_eq!(tier, None);
                assert!(exits.is_empty());
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_seed_info_with_spawn_items() {
        let json = r#"{"total_layers": 5, "event_ids": [100], "spawn_items": [{"id": 10500, "qty": 1}, {"id": 16300}]}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.spawn_items.len(), 2);
        assert_eq!(seed.spawn_items[0].id, 10500);
        assert_eq!(seed.spawn_items[0].qty, 1);
        assert_eq!(seed.spawn_items[1].id, 16300);
        assert_eq!(seed.spawn_items[1].qty, 1); // default
    }

    #[test]
    fn test_seed_info_without_spawn_items() {
        // Backward compat: old server sends no spawn_items field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.spawn_items.is_empty());
    }

    #[test]
    fn test_auth_ok_with_spawn_items() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5, "spawn_items": [{"id": 42, "qty": 2}]},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.spawn_items.len(), 1);
                assert_eq!(seed.spawn_items[0].id, 42);
                assert_eq!(seed.spawn_items[0].qty, 2);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_server_error_deserialize() {
        // Old server: no code field (wire contract pin).
        let json = r#"{"type": "error", "message": "Race not running"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { message, code } => {
                assert_eq!(message, "Race not running");
                assert_eq!(code, None);
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_server_error_deserialize_with_code() {
        let json = r#"{"type": "error", "message": "Wrong save loaded", "code": "wrong_save"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { code, .. } => {
                assert_eq!(code, Some(ConditionKind::WrongSave));
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_server_error_unknown_code_degrades_to_unknown() {
        // Wire pin: a code this build does not know must deserialize (not
        // fail) and classify as Unknown, i.e. the legacy transient path.
        let json = r#"{"type": "error", "message": "?", "code": "flux_capacitor"}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::Error { code, .. } => {
                assert_eq!(code, Some(ConditionKind::Unknown));
            }
            _ => panic!("Expected Error"),
        }
    }

    #[test]
    fn test_seed_info_with_seed_id() {
        let json = r#"{"total_layers": 5, "seed_id": "abc-123"}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.seed_id, Some("abc-123".to_string()));
    }

    #[test]
    fn test_seed_info_without_seed_id() {
        // Backward compat: old server sends no seed_id field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.seed_id, None);
    }

    #[test]
    fn test_seed_info_with_finish_event() {
        let json = r#"{"total_layers":5,"event_ids":[100,101],"finish_event":102}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.finish_event, Some(102));
    }

    #[test]
    fn test_seed_info_without_finish_event() {
        let json = r#"{"total_layers":5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.finish_event, None);
    }

    #[test]
    fn test_race_info_countdown_seconds_default() {
        // Backward compat: old server sends no countdown_seconds
        let json = r#"{"id": "123", "name": "Test", "status": "running"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.countdown_seconds, 0);
        assert_eq!(info.race_ends_at, None);
    }

    #[test]
    fn test_race_info_with_countdown_seconds() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "countdown_seconds": 10}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.countdown_seconds, 10);
    }

    #[test]
    fn test_race_info_with_seed_id() {
        // seed_id rides on race_info so the mod can spot a stale loaded pack
        // (e.g. after a reroll) outside the auth_ok handshake.
        let json = r#"{"id": "123", "name": "Test", "status": "running", "seed_id": "seed-xyz"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.seed_id.as_deref(), Some("seed-xyz"));
    }

    #[test]
    fn test_race_info_with_race_ends_at() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "race_ends_at": "2026-04-20T12:00:00Z"}"#;
        let info: RaceInfo = serde_json::from_str(json).unwrap();
        assert_eq!(info.race_ends_at.as_deref(), Some("2026-04-20T12:00:00Z"));
        // Cached parsed field is empty until reparse_dates() is called.
        assert!(info.race_ends_at_dt.is_none());
    }

    #[test]
    fn test_race_info_reparse_dates_populates_cache() {
        let json = r#"{"id": "123", "name": "Test", "status": "running", "race_ends_at": "2026-04-20T12:00:00Z"}"#;
        let mut info: RaceInfo = serde_json::from_str(json).unwrap();
        info.reparse_dates();
        let dt = info.race_ends_at_dt.expect("race_ends_at_dt populated");
        assert_eq!(dt.to_rfc3339(), "2026-04-20T12:00:00+00:00");
    }

    #[test]
    fn test_race_info_reparse_dates_handles_missing_and_invalid() {
        // Missing field: cache stays None.
        let mut info: RaceInfo =
            serde_json::from_str(r#"{"id": "123", "name": "Test", "status": "setup"}"#).unwrap();
        info.reparse_dates();
        assert!(info.race_ends_at_dt.is_none());

        // Garbage value: parse fails silently, cache stays None.
        let mut info: RaceInfo = serde_json::from_str(
            r#"{"id": "123", "name": "Test", "status": "setup", "race_ends_at": "not-a-date"}"#,
        )
        .unwrap();
        info.reparse_dates();
        assert!(info.race_ends_at_dt.is_none());
    }

    #[test]
    fn test_race_info_update_deserialize() {
        let json = r#"{
            "type": "race_info_update",
            "race": {
                "id": "123",
                "name": "Test",
                "status": "running",
                "race_ends_at": "2026-04-21T15:00:00Z"
            }
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::RaceInfoUpdate { race } => {
                assert_eq!(race.race_ends_at.as_deref(), Some("2026-04-21T15:00:00Z"));
                assert_eq!(race.status, RaceStatus::Running);
            }
            _ => panic!("Expected RaceInfoUpdate"),
        }
    }

    #[test]
    fn test_server_daily_streak_update_deserialize_ignores_payload() {
        // The mod does not consume daily_streak_update, but it must still
        // deserialize (otherwise it trips the "failed to parse" warning on
        // every broadcast) and drop the payload fields.
        let json = r#"{
            "type": "daily_streak_update",
            "current": 7,
            "best": 12,
            "freeze_count": 2,
            "freeze_consumed_for": "2026-06-06"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        assert_eq!(msg, ServerMessage::DailyStreakUpdate {});
    }

    #[test]
    fn test_auth_ok_with_seed_id() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5, "seed_id": "seed-xyz"},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { seed, .. } => {
                assert_eq!(seed.seed_id, Some("seed-xyz".to_string()));
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_client_zone_query_grace_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 60000,
            message_id: 42,
            grace_entity_id: Some(10002950),
            map_id: None,
            position: None,
            play_region_id: None,
            quit_out: false,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":60000"#));
        assert!(json.contains(r#""message_id":42"#));
        assert!(json.contains(r#""grace_entity_id":10002950"#));
        assert!(!json.contains("map_id"));
    }

    #[test]
    fn test_client_zone_query_map_only() {
        let msg = ClientMessage::ZoneQuery {
            igt_ms: 120000,
            message_id: 99,
            grace_entity_id: None,
            map_id: Some("m10_00_00_00".into()),
            position: Some([100.0, 50.0, 200.0]),
            play_region_id: Some(12345),
            quit_out: false,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""type":"zone_query""#));
        assert!(json.contains(r#""igt_ms":120000"#));
        assert!(json.contains(r#""message_id":99"#));
        assert!(json.contains(r#""map_id":"m10_00_00_00""#));
        assert!(!json.contains("grace_entity_id"));
    }

    #[test]
    fn test_client_zone_query_quit_out_serialization() {
        let mut msg = ClientMessage::ZoneQuery {
            igt_ms: 1000,
            message_id: 7,
            grace_entity_id: None,
            map_id: Some("m10_00_00_00".to_string()),
            position: Some([1.0, 2.0, 3.0]),
            play_region_id: None,
            quit_out: true,
        };
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains(r#""quit_out":true"#));

        // False is omitted from the wire (old servers never see the field).
        if let ClientMessage::ZoneQuery { quit_out, .. } = &mut msg {
            *quit_out = false;
        }
        let json = serde_json::to_string(&msg).unwrap();
        assert!(!json.contains("quit_out"));
    }

    #[test]
    fn test_race_info_old_server_defaults_quit_out_penalty() {
        // Wire-contract pin: a server that predates the field yields the
        // mod-side default of 2000 ms.
        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running"}"#).unwrap();
        assert_eq!(race.quit_out_penalty_ms, 2000);

        let race: RaceInfo = serde_json::from_str(
            r#"{"id":"r1","name":"x","status":"running","quit_out_penalty_ms":0}"#,
        )
        .unwrap();
        assert_eq!(race.quit_out_penalty_ms, 0);
    }

    #[test]
    fn test_server_zone_update_with_original_tier() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 2,
            "original_tier": 8,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                tier,
                original_tier,
                ..
            } => {
                assert_eq!(tier, Some(2));
                assert_eq!(original_tier, Some(8));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_with_layer() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "layer": 2,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { layer, .. } => {
                assert_eq!(layer, Some(2));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_layer() {
        // Backward compat: old server sends no layer field
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { layer, .. } => {
                assert_eq!(layer, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_original_tier() {
        // Backward compat: old server sends no original_tier field
        let json = r#"{
            "type": "zone_update",
            "node_id": "start_node",
            "display_name": "Chapel of Anticipation",
            "tier": null,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate {
                tier,
                original_tier,
                ..
            } => {
                assert_eq!(tier, None);
                assert_eq!(original_tier, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_participant_info_tier_defaults_none() {
        // Backward compat: old server sends no current_layer_tier field
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.current_layer_tier, None);
        // gap_ms also defaults to None when absent
        assert_eq!(p.gap_ms, None);
    }

    #[test]
    fn test_participant_info_with_gap_ms() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 2,
            "igt_ms": 90000,
            "death_count": 1,
            "gap_ms": 15000
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.gap_ms, Some(15000));
    }

    #[test]
    fn test_participant_info_gap_ms_null() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "gap_ms": null
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.gap_ms, None);
    }

    #[test]
    fn test_leaderboard_update_with_leader_splits() {
        let json = r#"{
            "type": "leaderboard_update",
            "participants": [],
            "leader_splits": {"0": 0, "1": 30000, "2": 75000}
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate {
                participants,
                leader_splits,
            } => {
                assert!(participants.is_empty());
                let splits = leader_splits.unwrap();
                assert_eq!(splits.get("0"), Some(&0));
                assert_eq!(splits.get("1"), Some(&30000));
                assert_eq!(splits.get("2"), Some(&75000));
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_leaderboard_update_without_leader_splits() {
        // Backward compat: old server sends no leader_splits
        let json = r#"{
            "type": "leaderboard_update",
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::LeaderboardUpdate { leader_splits, .. } => {
                assert_eq!(leader_splits, None);
            }
            _ => panic!("Expected LeaderboardUpdate"),
        }
    }

    #[test]
    fn test_participant_info_with_layer_entry_igt() {
        let json = r#"{
            "id": "1",
            "twitch_username": "player1",
            "twitch_display_name": null,
            "status": "playing",
            "current_zone": null,
            "current_layer": 2,
            "igt_ms": 90000,
            "death_count": 1,
            "gap_ms": 15000,
            "layer_entry_igt": 80000
        }"#;
        let p: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert_eq!(p.layer_entry_igt, Some(80000));
    }

    #[test]
    fn test_layer_entry_igts_string_keys_inside_a_server_message() {
        // JSON object keys are strings on the wire; the layers read as ints,
        // also once buffered by the internally tagged `ServerMessage`.
        let json = r#"{
            "type": "leaderboard_update",
            "participants": [{
                "id": "1",
                "twitch_username": "player1",
                "twitch_display_name": null,
                "status": "playing",
                "current_zone": null,
                "current_layer": 2,
                "igt_ms": 90000,
                "death_count": 1,
                "layer_entry_igt": 80000,
                "layer_entry_igts": {"0": 0, "1": 30000, "2": 80000}
            }, {
                "id": "2",
                "twitch_username": "player2",
                "twitch_display_name": null,
                "status": "ready",
                "current_zone": null,
                "current_layer": 0,
                "igt_ms": 0,
                "death_count": 0,
                "layer_entry_igts": null
            }]
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        let ServerMessage::LeaderboardUpdate { participants, .. } = msg else {
            panic!("Expected LeaderboardUpdate");
        };
        assert_eq!(
            participants[0].layer_entry_igts,
            Some(HashMap::from([(0, 0), (1, 30000), (2, 80000)]))
        );
        assert_eq!(participants[1].layer_entry_igts, None);
    }

    #[test]
    fn test_server_death_counts_deserialize() {
        let json = r#"{
            "type": "death_counts",
            "counts": {"node_a": 4, "node_b": 1}
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::DeathCounts { counts } => {
                assert_eq!(counts.get("node_a"), Some(&4));
                assert_eq!(counts.get("node_b"), Some(&1));
                assert_eq!(counts.len(), 2);
            }
            _ => panic!("Expected DeathCounts"),
        }
    }

    #[test]
    fn test_seed_info_with_death_flags() {
        let json = r#"{
            "total_layers": 5,
            "death_flags": {
                "node_a": [1040292500, 1040292501, 1040292502]
            }
        }"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        let flags = seed.death_flags.get("node_a").unwrap();
        assert_eq!(*flags, [1040292500, 1040292501, 1040292502]);
    }

    #[test]
    fn test_seed_info_without_death_flags() {
        // Backward compat: old server sends no death_flags field
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.death_flags.is_empty());
    }

    #[test]
    fn test_seed_info_with_items_spawned_flag() {
        let json = r#"{"total_layers": 5, "event_ids": [100], "items_spawned_flag": 1050290000}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.items_spawned_flag, Some(1050290000));
    }

    #[test]
    fn test_seed_info_without_items_spawned_flag() {
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.items_spawned_flag, None);
    }

    #[test]
    fn test_server_zone_update_with_message_id() {
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": [],
            "message_id": 42
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, Some(42));
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_update_without_message_id() {
        // Backward compat: old server sends no message_id field
        let json = r#"{
            "type": "zone_update",
            "node_id": "cave_e235",
            "display_name": "Cave of Knowledge",
            "tier": 5,
            "exits": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneUpdate { message_id, .. } => {
                assert_eq!(message_id, None);
            }
            _ => panic!("Expected ZoneUpdate"),
        }
    }

    #[test]
    fn test_server_zone_query_ack_deserialize() {
        let json = r#"{"type":"zone_query_ack","message_id":55}"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::ZoneQueryAck { message_id } => assert_eq!(message_id, 55),
            _ => panic!("Expected ZoneQueryAck"),
        }
    }

    #[test]
    fn test_participant_info_with_name_template_solid() {
        let json = r##"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "name_template": { "color": "#FFFFFF", "gradient": null }
        }"##;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        let nt = info.name_template.expect("name_template present");
        assert_eq!(nt.color.as_deref(), Some("#FFFFFF"));
        assert!(nt.gradient.is_none());
    }

    #[test]
    fn test_participant_info_with_name_template_gradient() {
        let json = r##"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0,
            "name_template": { "color": null, "gradient": ["#FFD700","#FFA500"] }
        }"##;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        let nt = info.name_template.unwrap();
        let g = nt.gradient.unwrap();
        assert_eq!(g, ("#FFD700".to_string(), "#FFA500".to_string()));
    }

    #[test]
    fn test_participant_info_without_name_template() {
        let json = r#"{
            "id": "p1",
            "twitch_username": "u",
            "twitch_display_name": null,
            "status": "registered",
            "current_zone": null,
            "current_layer": 0,
            "igt_ms": 0,
            "death_count": 0
        }"#;
        let info: ParticipantInfo = serde_json::from_str(json).unwrap();
        assert!(info.name_template.is_none());
    }

    #[test]
    fn test_auth_ok_with_phantom_skin() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "phantom_skin": "gold-aura"
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, Some("gold-aura".to_string()));
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_without_phantom_skin_field() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": []
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, None);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_auth_ok_with_phantom_skin_null() {
        let json = r#"{
            "type": "auth_ok",
            "participant_id": "abc-123",
            "race": {"id": "123", "name": "Test Race", "status": "setup"},
            "seed": {"total_layers": 5},
            "participants": [],
            "phantom_skin": null
        }"#;
        let msg: ServerMessage = serde_json::from_str(json).unwrap();
        match msg {
            ServerMessage::AuthOk { phantom_skin, .. } => {
                assert_eq!(phantom_skin, None);
            }
            _ => panic!("Expected AuthOk"),
        }
    }

    #[test]
    fn test_seed_info_with_phantom_skins() {
        let json = r#"{
            "total_layers": 5,
            "phantom_skins": {
                "gold-aura": {"speffects": [1450700]},
                "silver-aura": {"speffects": [1450705]}
            }
        }"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert_eq!(seed.phantom_skins.len(), 2);
        assert_eq!(seed.phantom_skins["gold-aura"].speffects, vec![1450700]);
        assert_eq!(seed.phantom_skins["silver-aura"].speffects, vec![1450705]);
    }

    #[test]
    fn test_seed_info_phantom_skins_defaults_empty() {
        let json = r#"{"total_layers": 5}"#;
        let seed: SeedInfo = serde_json::from_str(json).unwrap();
        assert!(seed.phantom_skins.is_empty());
    }

    #[test]
    fn test_phantom_skin_speffects_default_empty() {
        let json = r#"{}"#;
        let skin: PhantomSkin = serde_json::from_str(json).unwrap();
        assert!(skin.speffects.is_empty());
    }

    #[test]
    fn test_phantom_skin_unknown_keys_ignored() {
        // Forward-compat: the mod must tolerate future keys it doesn't know about.
        let json = r#"{"speffects": [1], "fxr_ids": [42], "future_field": "anything"}"#;
        let skin: PhantomSkin = serde_json::from_str(json).unwrap();
        assert_eq!(skin.speffects, vec![1]);
    }

    #[test]
    fn test_permanent_close_codes() {
        // Standard close codes: should reconnect
        assert!(!is_permanent_close(1000)); // Normal
        assert!(!is_permanent_close(1001)); // Going away
        assert!(!is_permanent_close(1006)); // Abnormal
        assert!(!is_permanent_close(1011)); // Server error
        assert!(!is_permanent_close(1012)); // Service restart

        // Boundary: 3999 is the last non-permanent code
        assert!(!is_permanent_close(3999));

        // Application close codes: permanent, do not reconnect
        assert!(is_permanent_close(4000)); // Boundary
        assert!(is_permanent_close(4001)); // Auth timeout
        assert!(is_permanent_close(4003)); // Auth error
        assert!(is_permanent_close(4004)); // Not found
        assert!(is_permanent_close(4999)); // Any future 4xxx code
    }

    #[test]
    fn test_status_enums_roundtrip_and_unknown() {
        // Known values keep today's lowercase wire strings.
        assert_eq!(
            serde_json::to_string(&RaceStatus::Running).unwrap(),
            "\"running\""
        );
        assert_eq!(
            serde_json::from_str::<RaceStatus>("\"setup\"").unwrap(),
            RaceStatus::Setup
        );
        assert_eq!(
            serde_json::to_string(&ParticipantStatus::Abandoned).unwrap(),
            "\"abandoned\""
        );
        // A status from a future server maps to Unknown instead of failing.
        assert_eq!(
            serde_json::from_str::<RaceStatus>("\"paused\"").unwrap(),
            RaceStatus::Unknown
        );
        assert_eq!(
            serde_json::from_str::<ParticipantStatus>("\"spectating\"").unwrap(),
            ParticipantStatus::Unknown
        );
    }

    #[test]
    fn race_info_deathless_defaults_false() {
        // Old-server wire contract: payload without the field.
        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running"}"#).unwrap();
        assert!(!race.deathless);

        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running","deathless":true}"#)
                .unwrap();
        assert!(race.deathless);
    }

    #[test]
    fn test_status_update_debug_flags_wire_shape() {
        let clean = ClientMessage::StatusUpdate {
            igt_ms: 1,
            death_count: 0,
            weapons: [None, None],
            debug_flags: vec![],
        };
        let json = serde_json::to_string(&clean).unwrap();
        assert!(!json.contains("debug_flags"), "omitted when empty: {json}");

        let flagged = ClientMessage::StatusUpdate {
            igt_ms: 1,
            death_count: 0,
            weapons: [None, None],
            debug_flags: vec!["one_shot".to_string()],
        };
        let json = serde_json::to_string(&flagged).unwrap();
        assert!(json.contains(r#""debug_flags":["one_shot"]"#), "{json}");
    }

    #[test]
    fn disqualified_status_deserializes() {
        let s: ParticipantStatus = serde_json::from_str(r#""disqualified""#).unwrap();
        assert_eq!(s, ParticipantStatus::Disqualified);
        assert!(s.is_out());
        let unknown: ParticipantStatus = serde_json::from_str(r#""a_future_status""#).unwrap();
        assert_eq!(unknown, ParticipantStatus::Unknown);
        assert!(!ParticipantStatus::Finished.is_out());
    }

    #[test]
    fn item_effect_damage_deserializes() {
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"item_effect","item":"red_shell",
            "effect":{"kind":"damage","base_pct":20,"floor_pct":20,"tail_pct":5},
            "banner":{"icon":"red_shell","title":"Red Shell","line":"Hit for 20% HP","detail":"from Gideohana"}}"#,
        )
        .unwrap();
        match msg {
            ServerMessage::ItemEffect {
                item,
                effect,
                banner,
                reminder,
            } => {
                assert_eq!(item, "red_shell");
                assert_eq!(
                    effect,
                    ItemEffectPayload::Damage {
                        base_pct: 20,
                        floor_pct: 20,
                        tail_pct: 5
                    }
                );
                let banner = banner.expect("a hit carries its banner");
                assert_eq!(banner.title, "Red Shell");
                assert_eq!(banner.detail, "from Gideohana");
                assert_eq!(reminder, None);
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn item_effect_speffect_ink_and_reminder() {
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"item_effect","item":"x","effect":{"kind":"speffect","speffect_id":4242},
            "banner":{"icon":"i","title":"t","line":"l","detail":"d"},
            "reminder":{"text":"Blue Shell","duration_ms":15000}}"#,
        )
        .unwrap();
        let ServerMessage::ItemEffect {
            effect, reminder, ..
        } = msg
        else {
            panic!("not an item_effect");
        };
        assert_eq!(
            effect,
            ItemEffectPayload::Speffect {
                speffect_id: 4242,
                duration_ms: None
            }
        );
        assert_eq!(
            reminder,
            Some(ItemReminder {
                text: "Blue Shell".into(),
                duration_ms: 15000
            })
        );
        let ink: ItemEffectPayload =
            serde_json::from_str(r#"{"kind":"ink","duration_ms":15000}"#).unwrap();
        assert_eq!(ink, ItemEffectPayload::Ink { duration_ms: 15000 });
        let load: ItemEffectPayload =
            serde_json::from_str(r#"{"kind":"equip_load","speffect_id":1450827,"load_pct":97}"#)
                .unwrap();
        assert_eq!(
            load,
            ItemEffectPayload::EquipLoad {
                speffect_id: 1450827,
                load_pct: 97,
                duration_ms: None
            }
        );
    }

    #[test]
    fn item_effect_duration_ms_is_optional() {
        // 1.14: a timed effect carries its duration.
        let timed: ItemEffectPayload = serde_json::from_str(
            r#"{"kind":"speffect","speffect_id":1450826,"duration_ms":30000}"#,
        )
        .unwrap();
        assert_eq!(
            timed,
            ItemEffectPayload::Speffect {
                speffect_id: 1450826,
                duration_ms: Some(30000)
            }
        );
        let load: ItemEffectPayload = serde_json::from_str(
            r#"{"kind":"equip_load","speffect_id":1450827,"load_pct":97,"duration_ms":15000}"#,
        )
        .unwrap();
        assert_eq!(
            load,
            ItemEffectPayload::EquipLoad {
                speffect_id: 1450827,
                load_pct: 97,
                duration_ms: Some(15000)
            }
        );
        // The 1.13 shape, and an instant effect (Rune Pouch) in 1.14: none.
        let instant: ItemEffectPayload =
            serde_json::from_str(r#"{"kind":"speffect","speffect_id":1450821}"#).unwrap();
        assert_eq!(
            instant,
            ItemEffectPayload::Speffect {
                speffect_id: 1450821,
                duration_ms: None
            }
        );
    }

    #[test]
    fn lightning_kind_parses() {
        // 1.18: the slow walk row and the size, for one duration.
        let effect: ItemEffectPayload = serde_json::from_str(
            r#"{"kind":"lightning","speffect_id":1450830,"duration_ms":15000,"scale_pct":50}"#,
        )
        .unwrap();
        assert_eq!(
            effect,
            ItemEffectPayload::Lightning {
                speffect_id: 1450830,
                scale_pct: 50,
                duration_ms: 15000
            }
        );
    }

    #[test]
    fn memory_effect_kinds_parse() {
        // 1.15: the memory effects, each with its duration.
        let parse = |json: &str| serde_json::from_str::<ItemEffectPayload>(json).unwrap();
        assert_eq!(
            parse(r#"{"kind":"vanish","duration_ms":15000}"#),
            ItemEffectPayload::Vanish { duration_ms: 15000 }
        );
        assert_eq!(
            parse(r#"{"kind":"unseen_foes","duration_ms":15000}"#),
            ItemEffectPayload::UnseenFoes { duration_ms: 15000 }
        );
        assert_eq!(
            parse(r#"{"kind":"slow_mo","duration_ms":15000,"speed_pct":50}"#),
            ItemEffectPayload::SlowMo {
                speed_pct: 50,
                duration_ms: 15000
            }
        );
        // The scale setting goes up to 300, past a byte.
        assert_eq!(
            parse(r#"{"kind":"scale","duration_ms":15000,"scale_pct":300}"#),
            ItemEffectPayload::Scale {
                scale_pct: 300,
                duration_ms: 15000
            }
        );
        for (wire, variant) in [
            ("first_person", CameraVariant::FirstPerson),
            ("inverted", CameraVariant::Inverted),
            ("wide", CameraVariant::Wide),
        ] {
            assert_eq!(
                parse(&format!(
                    r#"{{"kind":"camera","duration_ms":15000,"variant":"{wire}"}}"#
                )),
                ItemEffectPayload::Camera {
                    variant,
                    duration_ms: 15000
                },
                "{wire}"
            );
        }
    }

    #[test]
    fn lot_4_effect_kinds_parse() {
        // 1.17: the Talisman Thief (to the victim, then the gift to the
        // thief), the Junk Weapon and the Hunter.
        let parse = |json: &str| serde_json::from_str::<ItemEffectPayload>(json).unwrap();
        assert_eq!(
            parse(
                r#"{"kind":"steal_talisman","talismans":[{"id":1000,"flag":1050290300},
                    {"id":1001,"flag":1050290301}],"roll":4294967295,"report_id":12}"#
            ),
            ItemEffectPayload::StealTalisman {
                talismans: vec![
                    TalismanFlag {
                        id: 1000,
                        flag: 1_050_290_300
                    },
                    TalismanFlag {
                        id: 1001,
                        flag: 1_050_290_301
                    },
                ],
                roll: u32::MAX,
                report_id: 12,
            }
        );
        assert_eq!(
            parse(r#"{"kind":"talisman","talisman_id":1000}"#),
            ItemEffectPayload::Talisman { talisman_id: 1000 }
        );
        assert_eq!(
            parse(r#"{"kind":"junk_weapon","weapon_id":11010000}"#),
            ItemEffectPayload::JunkWeapon {
                weapon_id: 11_010_000
            }
        );
        assert_eq!(
            parse(
                r#"{"kind":"hunter","chr_id":2130,"npc_param_id":1450855,
                    "think_id":1450850,"duration_ms":60000,"report_id":13}"#
            ),
            ItemEffectPayload::Hunter {
                chr_id: 2130,
                npc_param_id: 1_450_855,
                think_id: 1_450_850,
                duration_ms: 60_000,
                report_id: 13,
            }
        );
    }

    #[test]
    fn item_report_sends_a_null_talisman_when_none_was_taken() {
        // The server reads a missing or null talisman_id the same; the wire
        // shape names it null.
        assert_eq!(
            serde_json::to_string(&ClientMessage::ItemReport {
                report_id: 13,
                landed: false,
                talisman_id: None,
            })
            .unwrap(),
            r#"{"type":"item_report","report_id":13,"landed":false,"talisman_id":null}"#
        );
        assert_eq!(
            serde_json::to_string(&ClientMessage::ItemReport {
                report_id: 12,
                landed: true,
                talisman_id: Some(1000),
            })
            .unwrap(),
            r#"{"type":"item_report","report_id":12,"landed":true,"talisman_id":1000}"#
        );
    }

    #[test]
    fn unknown_camera_variant_is_unknown() {
        // A variant from a later server: the message still parses (the
        // machine drops the effect).
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"item_effect","item":"camera",
                "effect":{"kind":"camera","duration_ms":15000,"variant":"fisheye"}}"#,
        )
        .unwrap();
        let ServerMessage::ItemEffect { effect, .. } = msg else {
            panic!("not an item_effect");
        };
        assert_eq!(
            effect,
            ItemEffectPayload::Camera {
                variant: CameraVariant::Unknown,
                duration_ms: 15000
            }
        );
    }

    #[test]
    fn item_notice_carries_a_banner() {
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"item_notice","banner":{"icon":"star","title":"Star",
                "line":"Blocked Red Shell","detail":"from bob"}}"#,
        )
        .unwrap();
        assert!(
            matches!(msg, ServerMessage::ItemNotice { ref banner } if banner.title == "Star"),
            "{msg:?}"
        );
    }

    #[test]
    fn unknown_effect_kind_is_unknown() {
        let effect: ItemEffectPayload =
            serde_json::from_str(r#"{"kind":"boo","ghost_ms":3}"#).unwrap();
        assert_eq!(effect, ItemEffectPayload::Unknown);
    }

    #[test]
    fn item_grant_and_result_deserialize() {
        let banner = r#""banner":{"icon":"i","title":"t","line":"l","detail":"d"}"#;
        let grant: ServerMessage = serde_json::from_str(&format!(
            r#"{{"type":"item_grant","grant_id":7,"item":"hammer",{banner}}}"#
        ))
        .unwrap();
        assert!(matches!(
            grant,
            ServerMessage::ItemGrant { grant_id: 7, ref item, .. } if item == "hammer"
        ));
        let result: ServerMessage = serde_json::from_str(&format!(
            r#"{{"type":"item_result","item":"hammer",{banner},"reminder":null}}"#
        ))
        .unwrap();
        assert!(matches!(
            result,
            ServerMessage::ItemResult { reminder: None, .. }
        ));
    }

    #[test]
    fn item_effect_without_banner_parses() {
        // A self item's effect (1.13): its banner rides on the item_result,
        // sent null or left out.
        for json in [
            r#"{"type":"item_effect","item":"mushroom","effect":{"kind":"speffect","speffect_id":1450826},"banner":null}"#,
            r#"{"type":"item_effect","item":"mushroom","effect":{"kind":"speffect","speffect_id":1450826}}"#,
        ] {
            let msg: ServerMessage = serde_json::from_str(json).unwrap();
            let ServerMessage::ItemEffect {
                effect,
                banner,
                reminder,
                ..
            } = msg
            else {
                panic!("not an item_effect: {json}");
            };
            assert_eq!(
                effect,
                ItemEffectPayload::Speffect {
                    speffect_id: 1450826,
                    duration_ms: None
                }
            );
            assert_eq!(banner, None, "{json}");
            assert_eq!(reminder, None, "{json}");
        }
    }

    #[test]
    fn item_remove_names_a_goods() {
        let banner = r#""banner":{"icon":"i","title":"t","line":"l","detail":"d"}"#;
        for (json, has_banner) in [
            (
                r#"{"type":"item_remove","goods":"shield","banner":null}"#.to_string(),
                false,
            ),
            (
                r#"{"type":"item_remove","goods":"race_item"}"#.to_string(),
                false,
            ),
            (
                format!(r#"{{"type":"item_remove","goods":"shield",{banner}}}"#),
                true,
            ),
        ] {
            let msg: ServerMessage = serde_json::from_str(&json).unwrap();
            let ServerMessage::ItemRemove { goods, banner } = msg else {
                panic!("not an item_remove: {json}");
            };
            assert!(goods == "shield" || goods == "race_item", "{json}");
            assert_eq!(banner.is_some(), has_banner, "{json}");
        }
    }

    #[test]
    fn auth_ok_held_item_defaults_to_none() {
        let auth = |extra: &str| {
            format!(
                r#"{{"type":"auth_ok","participant_id":"p",
                "race":{{"id":"r","name":"R","status":"running","race_items":true}},
                "seed":{{"total_layers":3}},"participants":[]{extra}}}"#
            )
        };
        let held = |json: &str| match serde_json::from_str::<ServerMessage>(json).unwrap() {
            ServerMessage::AuthOk { held_item, .. } => held_item,
            other => panic!("unexpected {other:?}"),
        };
        // A pre-1.13 server, and a runner holding nothing.
        assert_eq!(held(&auth("")), None);
        assert_eq!(held(&auth(r#","held_item":null"#)), None);
        assert_eq!(
            held(&auth(r#","held_item":"hammer""#)).as_deref(),
            Some("hammer")
        );
    }

    #[test]
    fn seed_catalog_v2_parses_goods_and_items() {
        // The 1.13 wire shape, graph.json's extra keys (goods icon, item
        // effect) included: unknown fields are ignored.
        let seed: SeedInfo = serde_json::from_str(
            r#"{"total_layers":3,"race_item_catalog":{
            "goods":{
              "race_item":{"goods_id":1450801,"use_flag":1050290101,"remove_flag":1050290201,
                           "icon":"item_box","icon_id":60396},
              "shield":{"goods_id":1450800,"use_flag":null,"remove_flag":1050290200,
                        "icon_id":60385}},
            "items":{
              "hammer":{"name":"Hammer","icon":"hammer","icon_id":60390,"goods":"race_item",
                        "effect_speffect":1450827,"duration_ms":15000},
              "shield":{"name":"Shield","icon":"shield","icon_id":60385,"goods":"shield"}}}}"#,
        )
        .unwrap();
        let catalog = &seed.race_item_catalog;
        assert_eq!(
            catalog.goods["race_item"],
            RaceItemGoods {
                goods_id: 1450801,
                use_flag: Some(1050290101),
                remove_flag: 1050290201,
                icon_id: 60396,
            }
        );
        assert_eq!(catalog.goods["shield"].use_flag, None);
        assert_eq!(
            catalog.items["hammer"],
            RaceItemEntry {
                name: "Hammer".into(),
                icon: "hammer".into(),
                icon_id: 60390,
                goods: "race_item".into(),
            }
        );
        assert_eq!(catalog.items["shield"].goods, "shield");

        // An old server: no catalog, or the 1.12 per-item shape, whose keys
        // are no catalog field: no race item at all, the auth still parses.
        let old: SeedInfo = serde_json::from_str(r#"{"total_layers":3}"#).unwrap();
        assert!(old.race_item_catalog.goods.is_empty() && old.race_item_catalog.items.is_empty());
        let v1: SeedInfo = serde_json::from_str(
            r#"{"total_layers":3,"race_item_catalog":{
            "shield":{"goods_id":1450800,"use_flag":null,"remove_flag":1050290200,
                      "name":"Shield","icon":"shield"}}}"#,
        )
        .unwrap();
        assert!(v1.race_item_catalog.goods.is_empty() && v1.race_item_catalog.items.is_empty());
    }

    #[test]
    fn seed_catalog_empty_object_is_no_catalog() {
        // What the server sends for a race without items: `{}`, so that a
        // 1.12 mod (which reads the field as a map of items) parses it too.
        let seed: SeedInfo =
            serde_json::from_str(r#"{"total_layers":3,"race_item_catalog":{}}"#).unwrap();
        assert_eq!(seed.race_item_catalog, RaceItemCatalog::default());
    }

    #[test]
    fn race_info_without_race_items_defaults_false() {
        // Pre-1.12 server wire contract: payload without the field.
        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running"}"#).unwrap();
        assert!(!race.race_items);
        let race: RaceInfo =
            serde_json::from_str(r#"{"id":"r1","name":"x","status":"running","race_items":true}"#)
                .unwrap();
        assert!(race.race_items);
    }

    #[test]
    fn item_inventory_serializes_goods() {
        assert_eq!(
            serde_json::to_string(&ClientMessage::ItemInventory {
                goods: vec!["race_item".into(), "shield".into()]
            })
            .unwrap(),
            r#"{"type":"item_inventory","goods":["race_item","shield"]}"#
        );
    }

    #[test]
    fn item_client_messages_serialize() {
        assert_eq!(
            serde_json::to_string(&ClientMessage::ItemReceived { grant_id: 7 }).unwrap(),
            r#"{"type":"item_received","grant_id":7}"#
        );
    }

    // ---- Relay (protocol 1.19) ----

    const RELAY_INFO: &str = r#"{"team_id":"t1","team_name":"Red Team","team_status":"playing","cap":5,
      "holder_id":"p2","holder_online":true,"zone_name":"Stormveil Castle","baton_free_in_s":null,
      "role":"waiting","gates_locked":false,
      "members":[{"participant_id":"p1","name":"Roger","zones":2,"status":"playing","online":true,"ready":true,"validated":true},
                 {"participant_id":"p2","name":"Kahleeya","zones":3,"status":"playing","online":true,"ready":false,"validated":true}],
      "flags":{"lock_flag":1050290500,"chapel_warp_flag":1050290501,"warp_flag_base":1050290510,"zone_flag_base":1050294000,"travel_lock_flag":1050290503,"roundtable_warp_flag":1050290504,"token_flag_base":1050297900,"token_bits":24}}"#;
    const RELAY_STATE: &str = r#"{"grace_flags":[71000,76101]}"#;
    const AUTH_OK_BASE: &str = r#""type":"auth_ok","participant_id":"abc-123",
        "race":{"id":"123","name":"Test Race","status":"setup"},
        "seed":{"total_layers":5},"participants":[]"#;

    #[test]
    fn relay_update_parses_the_contract_payload() {
        let msg: ServerMessage = serde_json::from_str(&format!(
            r#"{{"type":"relay_update","relay":{RELAY_INFO}}}"#
        ))
        .unwrap();
        let ServerMessage::RelayUpdate { relay } = msg else {
            panic!("{msg:?}")
        };
        assert_eq!(
            (relay.role, relay.team_status),
            (RelayRole::Waiting, ParticipantStatus::Playing)
        );
        assert_eq!(
            (relay.cap, relay.flags.lock_flag, relay.flags.zone_flag_base),
            (5, 1050290500, 1050294000)
        );
        assert_eq!(relay.members[1].name, "Kahleeya");
        assert_eq!(relay.zone_name.as_deref(), Some("Stormveil Castle"));
        assert!(relay.members[0].ready && !relay.members[1].ready);
        assert!(relay.baton_free_in_s.is_none());
        // A message of the earlier shape carries no token: read as unbound.
        assert_eq!((relay.token, relay.bound), (None, false));
    }

    #[test]
    fn relay_loot_parses_with_and_without_an_announce() {
        let live = r#"{"type":"relay_loot","paid":false,
            "announce":{"runner":"Kahleeya","boss":"Godrick the Grafted"},
            "entries":[{"flag":10000800,"received_flag":1050297000,"pickup_flags":[510060],
                        "items":[{"id":536874924,"qty":1}],"rune_speffect":755891000,"runes":13000}]}"#;
        let ServerMessage::RelayLoot {
            entries,
            paid,
            announce,
        } = serde_json::from_str(live).unwrap()
        else {
            panic!()
        };
        assert!(!paid);
        assert_eq!(announce.unwrap().boss, "Godrick the Grafted");
        assert_eq!(
            entries[0].items[0],
            RelayLootItem {
                id: 0x2000_0000 | 4012,
                qty: 1
            }
        );
        let list = r#"{"type":"relay_loot","paid":true,"announce":null,
            "entries":[{"flag":1,"received_flag":2,"pickup_flags":[],"items":[],"rune_speffect":null,"runes":0}]}"#;
        assert!(matches!(
            serde_json::from_str(list).unwrap(),
            ServerMessage::RelayLoot {
                paid: true,
                announce: None,
                ..
            }
        ));
    }

    #[test]
    fn relay_bound_serializes_with_its_token() {
        assert_eq!(
            serde_json::to_string(&ClientMessage::RelayBound { token: 4242 }).unwrap(),
            r#"{"type":"relay_bound","token":4242}"#
        );
    }

    #[test]
    fn a_relay_info_without_the_new_flags_is_refused() {
        // The 4.15 flags: a seed of the old shape must not be read as a relay.
        let old = RELAY_INFO.replace(r#","travel_lock_flag":1050290503"#, "");
        assert_ne!(old, RELAY_INFO);
        assert!(serde_json::from_str::<RelayInfo>(&old).is_err());
    }

    #[test]
    fn relay_take_parses_with_and_without_a_state() {
        let full: ServerMessage = serde_json::from_str(&format!(
            r#"{{"type":"relay_take","handoff_id":"h1","state":{RELAY_STATE},"igt_ms":2634000,
                "defeat_flags":[10000800],"warp_flag":1050290517,"zone_name":"Stormveil Castle"}}"#
        ))
        .unwrap();
        let ServerMessage::RelayTake {
            state, warp_flag, ..
        } = full
        else {
            panic!()
        };
        assert_eq!(state.unwrap().grace_flags, vec![71000, 76101]);
        assert_eq!(warp_flag, Some(1050290517));
        let bare: ServerMessage = serde_json::from_str(
            r#"{"type":"relay_take","handoff_id":"h1","state":null,"igt_ms":0,"defeat_flags":[],"warp_flag":null,"zone_name":null}"#,
        )
        .unwrap();
        assert!(matches!(
            bare,
            ServerMessage::RelayTake {
                state: None,
                warp_flag: None,
                zone_name: None,
                ..
            }
        ));
    }

    #[test]
    fn a_state_of_the_old_shape_reads_as_its_graces() {
        let old = r#"{"attributes":[40,20,25,30,14,9,9,7],"level":68,"runes":15230,
                      "items":[2000005,2147493648],"grace_flags":[71000,76101]}"#;
        let state: CharacterState = serde_json::from_str(old).unwrap();
        assert_eq!(state.grace_flags, vec![71000, 76101]);
        assert_eq!(
            serde_json::to_string(&state).unwrap(),
            r#"{"grace_flags":[71000,76101]}"#
        );
    }

    #[test]
    fn relay_client_messages_serialize() {
        let json = |m: &ClientMessage| serde_json::to_string(m).unwrap();
        assert_eq!(
            json(&ClientMessage::RelayReady { ready: true }),
            r#"{"type":"relay_ready","ready":true}"#
        );
        assert_eq!(
            json(&ClientMessage::RelayHandoffRequest {
                to_participant_id: "p2".into()
            }),
            r#"{"type":"relay_handoff_request","to_participant_id":"p2"}"#
        );
        assert_eq!(
            json(&ClientMessage::RelayTakeRequest),
            r#"{"type":"relay_take_request"}"#
        );
        assert_eq!(
            json(&ClientMessage::RelayTaken {
                handoff_id: "h1".into()
            }),
            r#"{"type":"relay_taken","handoff_id":"h1"}"#
        );
        let state: CharacterState = serde_json::from_str(RELAY_STATE).unwrap();
        let checkpoint = json(&ClientMessage::RelayState {
            handoff_id: None,
            state,
            igt_ms: 7,
        });
        assert!(checkpoint.contains(r#""handoff_id":null"#));
        assert!(checkpoint.contains(r#""state":{"grace_flags":[71000,76101]}"#));
    }

    #[test]
    fn relay_release_and_refused_parse() {
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"relay_release","handoff_id":"h1","to_name":"Kahleeya"}"#,
        )
        .unwrap();
        assert_eq!(
            msg,
            ServerMessage::RelayRelease {
                handoff_id: "h1".into(),
                to_name: "Kahleeya".into()
            }
        );
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"relay_refused","code":"target_at_cap","message":"This teammate has reached their zone quota"}"#,
        )
        .unwrap();
        assert_eq!(
            msg,
            ServerMessage::RelayRefused {
                code: "target_at_cap".into(),
                message: "This teammate has reached their zone quota".into()
            }
        );
    }

    #[test]
    fn auth_ok_carries_relay_or_none() {
        let with: ServerMessage =
            serde_json::from_str(&format!(r#"{{{AUTH_OK_BASE},"relay":{RELAY_INFO}}}"#)).unwrap();
        let ServerMessage::AuthOk { relay, .. } = with else {
            panic!()
        };
        assert_eq!(relay.unwrap().team_id, "t1");
        for extra in [r#","relay":null"#, ""] {
            let msg: ServerMessage =
                serde_json::from_str(&format!("{{{AUTH_OK_BASE}{extra}}}")).unwrap();
            let ServerMessage::AuthOk { relay, .. } = msg else {
                panic!()
            };
            assert!(relay.is_none(), "{extra:?}");
        }
    }

    #[test]
    fn relay_info_of_setup_parses() {
        let json = RELAY_INFO
            .replace(
                r#""team_status":"playing""#,
                r#""team_status":"registered""#,
            )
            .replace(r#""holder_id":"p2""#, r#""holder_id":null"#)
            .replace(r#""holder_online":true"#, r#""holder_online":false"#)
            .replace(
                r#""zone_name":"Stormveil Castle","baton_free_in_s":null"#,
                r#""zone_name":"Chapel of Anticipation","baton_free_in_s":0"#,
            );
        let msg: ServerMessage =
            serde_json::from_str(&format!(r#"{{"type":"relay_update","relay":{json}}}"#)).unwrap();
        let ServerMessage::RelayUpdate { relay } = msg else {
            panic!()
        };
        assert_eq!(relay.team_status, ParticipantStatus::Registered);
        assert!(relay.holder_id.is_none());
        assert_eq!(relay.baton_free_in_s, Some(0));
        assert_eq!(relay.zone_name.as_deref(), Some("Chapel of Anticipation"));
    }

    #[test]
    fn relay_info_tolerates_unknowns_and_missing_member_flags() {
        let json = RELAY_INFO
            .replace(r#""role":"waiting""#, r#""role":"captain","new_field":1"#)
            .replace(
                r#""team_status":"playing""#,
                r#""team_status":"a_future_status""#,
            )
            .replace(r#","ready":false,"validated":true"#, "");
        let msg: ServerMessage =
            serde_json::from_str(&format!(r#"{{"type":"relay_update","relay":{json}}}"#)).unwrap();
        let ServerMessage::RelayUpdate { relay } = msg else {
            panic!()
        };
        assert_eq!(relay.role, RelayRole::Unknown);
        assert_eq!(relay.team_status, ParticipantStatus::Unknown);
        // A member whose readiness is absent offers nothing.
        assert!(!relay.members[1].ready && !relay.members[1].validated);
    }

    #[test]
    fn relay_leaderboard_rows_parse() {
        let msg: ServerMessage = serde_json::from_str(
            r#"{"type":"leaderboard_update","participants":[{"id":"t1","twitch_username":"red",
                "twitch_display_name":"Red Team","status":"playing","current_zone":"Limgrave",
                "current_layer":2,"current_layer_tier":3,"igt_ms":60000,"death_count":1,
                "relay_holder":"Kahleeya","relay_holder_id":"p2","relay_cap":5,
                "relay_members":[{"participant_id":"p1","name":"Roger","zones":2,"status":"playing","online":true}]}]}"#,
        )
        .unwrap();
        let ServerMessage::LeaderboardUpdate { participants, .. } = msg else {
            panic!()
        };
        assert_eq!(participants[0].id, "t1");
    }
}
