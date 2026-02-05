//! Race tracker - main orchestrator for SpeedFog Racing mod
//!
//! Tracks player progress and communicates with the racing server.

use std::time::{Duration, Instant};
use tracing::{debug, error, info, warn};
use windows::Win32::Foundation::HINSTANCE;

use crate::core::protocol::{ParticipantInfo, RaceInfo, SeedInfo};
use crate::core::traits::GameStateReader;
use crate::eldenring::GameState;

use super::config::RaceConfig;
use super::hotkey::begin_hotkey_frame;
use super::websocket::{ConnectionStatus, IncomingMessage, RaceWebSocketClient};

// =============================================================================
// RACE STATE
// =============================================================================

/// Current race state from server
#[derive(Debug, Clone, Default)]
pub struct RaceState {
    pub race: Option<RaceInfo>,
    pub seed: Option<SeedInfo>,
    pub participants: Vec<ParticipantInfo>,
    pub race_started: bool,
}

// =============================================================================
// RACE TRACKER
// =============================================================================

pub struct RaceTracker {
    // Game reader
    game_state: GameState,

    // WebSocket
    pub(crate) ws_client: RaceWebSocketClient,

    // Config
    pub(crate) config: RaceConfig,

    // Race state
    pub(crate) race_state: RaceState,

    // UI state
    pub(crate) show_ui: bool,

    // Player state tracking
    last_zone: Option<String>,
    last_layer: Option<u8>,

    // Status update throttle
    last_status_update: Instant,

    // Ready sent flag
    ready_sent: bool,
}

impl RaceTracker {
    pub fn new(hmodule: HINSTANCE) -> Option<Self> {
        info!("Initializing RaceTracker...");

        // Load config
        let config = match RaceConfig::load(hmodule) {
            Ok(cfg) => cfg,
            Err(e) => {
                error!(error = %e, "Failed to load config");
                return None;
            }
        };

        if !config.is_valid() {
            error!("Config is invalid (missing server/mod_token/race_id)");
            return None;
        }

        // Init game state
        let game_state = GameState::new();
        game_state.wait_for_game_loaded();

        // Create WebSocket client
        let mut ws_client = RaceWebSocketClient::new(config.server.clone());
        ws_client.connect();

        info!("RaceTracker initialized");

        Some(Self {
            game_state,
            ws_client,
            config,
            race_state: RaceState::default(),
            show_ui: true,
            last_zone: None,
            last_layer: None,
            last_status_update: Instant::now(),
            ready_sent: false,
        })
    }

    pub fn update(&mut self) {
        // Process hotkeys at start of frame
        begin_hotkey_frame();

        // Check toggle_ui hotkey
        if self.config.keybindings.toggle_ui.is_just_pressed() {
            self.show_ui = !self.show_ui;
            info!(show_ui = self.show_ui, "[HOTKEY] Toggle UI");
        }

        // Poll WebSocket
        while let Some(msg) = self.ws_client.poll() {
            self.handle_ws_message(msg);
        }

        // Skip game reading if not connected
        if !self.ws_client.is_connected() {
            return;
        }

        // Read game state
        let igt_ms = self.game_state.read_igt().unwrap_or(0);
        let deaths = self.game_state.read_deaths().unwrap_or(0);
        let current_zone = self.read_current_zone();
        let current_layer = self.calculate_layer();

        // Send ready once connected (if not already sent)
        if !self.ready_sent {
            self.ws_client.send_ready();
            self.ready_sent = true;
            info!("[RACE] Sent ready signal");
        }

        // Detect zone changes
        if let Some(ref zone) = current_zone {
            if self.last_zone.as_ref() != Some(zone) {
                let from_zone = self.last_zone.clone().unwrap_or_default();
                info!(from = %from_zone, to = %zone, "[RACE] Zone change");
                self.ws_client
                    .send_zone_entered(from_zone, zone.clone(), igt_ms);
                self.last_zone = Some(zone.clone());
            }
        }

        // Track layer changes
        if self.last_layer != Some(current_layer) {
            info!(layer = current_layer, "[RACE] Layer change");
            self.last_layer = Some(current_layer);
        }

        // Send periodic status updates (every 1 second)
        if self.last_status_update.elapsed() >= Duration::from_secs(1) {
            self.ws_client.send_status_update(
                igt_ms,
                current_zone.clone().unwrap_or_default(),
                current_layer,
                deaths,
            );
            self.last_status_update = Instant::now();
        }
    }

    fn handle_ws_message(&mut self, msg: IncomingMessage) {
        match msg {
            IncomingMessage::StatusChanged(status) => {
                info!(status = ?status, "[WS] Status changed");
                if status == ConnectionStatus::Connected {
                    self.ready_sent = false; // Reset for reconnection
                }
            }
            IncomingMessage::AuthOk {
                race,
                seed,
                participants,
            } => {
                info!(race = %race.name, participants = participants.len(), "[WS] Auth OK");
                self.race_state.race = Some(race);
                self.race_state.seed = Some(seed);
                self.race_state.participants = participants;
            }
            IncomingMessage::AuthError(msg) => {
                error!(message = %msg, "[WS] Auth failed");
            }
            IncomingMessage::RaceStart => {
                info!("[WS] Race started!");
                self.race_state.race_started = true;
            }
            IncomingMessage::LeaderboardUpdate(participants) => {
                debug!(count = participants.len(), "[WS] Leaderboard update");
                self.race_state.participants = participants;
            }
            IncomingMessage::RaceStatusChange(status) => {
                info!(status = %status, "[WS] Race status changed");
                if let Some(ref mut race) = self.race_state.race {
                    race.status = status;
                }
            }
            IncomingMessage::PlayerUpdate(player) => {
                // Update single player in list
                if let Some(p) = self
                    .race_state
                    .participants
                    .iter_mut()
                    .find(|p| p.id == player.id)
                {
                    *p = player;
                }
            }
            IncomingMessage::Error(e) => {
                warn!(error = %e, "[WS] Error");
            }
        }
    }

    fn read_current_zone(&self) -> Option<String> {
        // For now, use map_id as zone identifier
        // TODO: Integrate with zone tracking when seed data is available
        let pos = self.game_state.read_position()?;
        Some(pos.map_id_str.clone())
    }

    fn calculate_layer(&self) -> u8 {
        // Placeholder - would need to track discovered links vs graph
        // For now return 0
        0
    }

    // Public getters for UI
    pub fn ws_status(&self) -> ConnectionStatus {
        self.ws_client.status()
    }

    pub fn race_info(&self) -> Option<&RaceInfo> {
        self.race_state.race.as_ref()
    }

    pub fn seed_info(&self) -> Option<&SeedInfo> {
        self.race_state.seed.as_ref()
    }

    pub fn participants(&self) -> &[ParticipantInfo] {
        &self.race_state.participants
    }

    pub fn read_igt(&self) -> Option<u32> {
        self.game_state.read_igt()
    }

    pub fn read_deaths(&self) -> Option<u32> {
        self.game_state.read_deaths()
    }

    pub fn current_zone(&self) -> Option<&str> {
        self.last_zone.as_deref()
    }
}
