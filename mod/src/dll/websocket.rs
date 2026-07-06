//! WebSocket client for SpeedFog Racing server
//!
//! Handles connection, authentication, and race message exchange.

use crossbeam_channel::{bounded, Receiver, Sender, TryRecvError};
use std::collections::HashMap;
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};
use tracing::{error, info, warn};
use tungstenite::stream::MaybeTlsStream;
use tungstenite::{connect, Message, WebSocket};

use super::config::ServerSettings;
use crate::core::protocol::{
    is_permanent_close, ClientMessage, ExitInfo, ParticipantInfo, RaceInfo, SeedInfo,
    ServerMessage, PROTOCOL_VERSION,
};
use crate::profile_span;

// =============================================================================
// TYPES
// =============================================================================

// Re-exported so existing `super::websocket::ConnectionStatus` imports keep
// working; the type itself lives in the platform-independent core.
pub use crate::core::race_machine::{ConnectionStatus, MachineMessage};

/// Outgoing messages (main thread -> WS thread)
#[derive(Debug)]
pub enum OutgoingMessage {
    Ready,
    StatusUpdate {
        igt_ms: u32,
        death_count: u32,
        weapons: [Option<i32>; 2],
    },
    EventFlag {
        flag_id: u32,
        igt_ms: u32,
        message_id: u64,
    },
    ZoneQuery {
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
    },
    Shutdown,
}

// =============================================================================
// WEBSOCKET CLIENT
// =============================================================================

/// Thread-safe WebSocket client for racing server
pub struct RaceWebSocketClient {
    settings: ServerSettings,
    tx: Option<Sender<OutgoingMessage>>,
    rx: Option<Receiver<MachineMessage>>,
    thread_handle: Option<JoinHandle<()>>,
    shutdown_flag: Arc<AtomicBool>,
    current_status: ConnectionStatus,
}

impl RaceWebSocketClient {
    pub fn new(settings: ServerSettings) -> Self {
        Self {
            settings,
            tx: None,
            rx: None,
            thread_handle: None,
            shutdown_flag: Arc::new(AtomicBool::new(false)),
            current_status: ConnectionStatus::Disconnected,
        }
    }

    pub fn is_enabled(&self) -> bool {
        !self.settings.url.is_empty()
            && !self.settings.mod_token.is_empty()
            && !self.settings.race_id.is_empty()
    }

    pub fn connect(&mut self) {
        if !self.is_enabled() {
            warn!("[WS] Missing config, not connecting");
            return;
        }

        if self.thread_handle.is_some() {
            warn!("[WS] Already running");
            return;
        }

        let (outgoing_tx, outgoing_rx) = bounded::<OutgoingMessage>(128);
        let (incoming_tx, incoming_rx) = bounded::<MachineMessage>(128);

        self.tx = Some(outgoing_tx);
        self.rx = Some(incoming_rx);
        self.shutdown_flag.store(false, Ordering::SeqCst);

        let shutdown_flag = Arc::clone(&self.shutdown_flag);
        let settings = self.settings.clone();

        let handle = thread::spawn(move || {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                websocket_thread(settings, outgoing_rx, incoming_tx.clone(), shutdown_flag);
            }));

            if let Err(panic_info) = result {
                let msg = format!(
                    "WS thread panic: {}",
                    crate::panic_message(panic_info.as_ref())
                );
                error!("{}", msg);
                let _ = incoming_tx.send(MachineMessage::Error(msg));
                let _ = incoming_tx.send(MachineMessage::StatusChanged(ConnectionStatus::Error));
            }
        });

        self.thread_handle = Some(handle);
        self.current_status = ConnectionStatus::Connecting;
    }

    pub fn disconnect(&mut self) {
        self.shutdown_flag.store(true, Ordering::SeqCst);
        if let Some(tx) = &self.tx {
            let _ = tx.send(OutgoingMessage::Shutdown);
        }
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }
        self.tx = None;
        self.rx = None;
        self.current_status = ConnectionStatus::Disconnected;
    }

    pub fn send_ready(&self) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::Ready) {
                warn!("[WS] Failed to queue message: {}", e);
            }
        }
    }

    pub fn send_status_update(&self, igt_ms: u32, death_count: u32, weapons: [Option<i32>; 2]) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::StatusUpdate {
                igt_ms,
                death_count,
                weapons,
            }) {
                warn!("[WS] Failed to queue message: {}", e);
            }
        }
    }

    pub fn send_event_flag(&self, flag_id: u32, igt_ms: u32, message_id: u64) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::EventFlag {
                flag_id,
                igt_ms,
                message_id,
            }) {
                warn!("[WS] Failed to queue message: {}", e);
            }
        }
    }

    pub fn send_zone_query(
        &self,
        igt_ms: u32,
        grace_entity_id: Option<u32>,
        map_id: Option<String>,
        position: Option<[f32; 3]>,
        play_region_id: Option<u32>,
        message_id: u64,
    ) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::ZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            }) {
                warn!("[WS] Failed to queue zone_query: {}", e);
            }
        }
    }

    pub fn poll(&mut self) -> Option<MachineMessage> {
        let rx = self.rx.as_ref()?;
        match rx.try_recv() {
            Ok(msg) => {
                if let MachineMessage::StatusChanged(status) = &msg {
                    self.current_status = *status;
                }
                Some(msg)
            }
            Err(TryRecvError::Empty) => None,
            Err(TryRecvError::Disconnected) => {
                self.current_status = ConnectionStatus::Disconnected;
                None
            }
        }
    }

    pub fn status(&self) -> ConnectionStatus {
        self.current_status
    }

    pub fn is_connected(&self) -> bool {
        self.current_status == ConnectionStatus::Connected
    }
}

impl Drop for RaceWebSocketClient {
    fn drop(&mut self) {
        self.disconnect();
    }
}

// =============================================================================
// WEBSOCKET THREAD
// =============================================================================

fn websocket_thread(
    settings: ServerSettings,
    outgoing_rx: Receiver<OutgoingMessage>,
    incoming_tx: Sender<MachineMessage>,
    shutdown_flag: Arc<AtomicBool>,
) {
    #[cfg(feature = "profile-tracy")]
    tracy_client::set_thread_name!("ws-worker");
    profile_span!("ws_thread");

    let mut reconnect_delay = Duration::from_secs(1);
    let max_delay = Duration::from_secs(30);
    let mut consecutive_failures: u32 = 0;
    let mut last_disconnect_reason: Option<String> = None;
    let stop_reconnect = AtomicBool::new(false);

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            break;
        }

        // Build URL
        let base = settings.url.trim_end_matches('/');
        let ws_base = if base.starts_with("https://") {
            base.replacen("https://", "wss://", 1)
        } else if base.starts_with("http://") {
            base.replacen("http://", "ws://", 1)
        } else {
            base.to_string()
        };
        let endpoint = if settings.training { "training" } else { "mod" };
        let url = format!("{}/ws/{}/{}", ws_base, endpoint, settings.race_id);

        info!(url = %url, "[WS] Connecting...");
        let _ = incoming_tx.send(MachineMessage::StatusChanged(ConnectionStatus::Connecting));

        match connect_and_auth(&url, &settings.mod_token, &incoming_tx) {
            Ok(mut socket) => {
                if consecutive_failures > 0 {
                    info!(
                        after_failures = consecutive_failures,
                        "[WS] Connected and authenticated (recovered)"
                    );
                } else {
                    info!("[WS] Connected and authenticated");
                }
                consecutive_failures = 0;

                // Drain stale outgoing messages before notifying Connected.
                // During disconnection, status_update messages pile up in the channel;
                // sending them before Ready would confuse the server.
                let mut drained = 0u32;
                while let Ok(msg) = outgoing_rx.try_recv() {
                    match msg {
                        OutgoingMessage::Shutdown => {
                            let _ = incoming_tx.send(MachineMessage::StatusChanged(
                                ConnectionStatus::Disconnected,
                            ));
                            return;
                        }
                        OutgoingMessage::EventFlag {
                            flag_id,
                            igt_ms,
                            message_id,
                        } => {
                            // Re-queue event flags back to the tracker for re-buffering.
                            // These were queued but never transmitted before disconnect.
                            let _ = incoming_tx.send(MachineMessage::RequeueEventFlag {
                                flag_id,
                                igt_ms,
                                message_id,
                            });
                        }
                        OutgoingMessage::ZoneQuery {
                            igt_ms,
                            grace_entity_id,
                            map_id,
                            position,
                            play_region_id,
                            message_id,
                        } => {
                            let _ = incoming_tx.send(MachineMessage::RequeueZoneQuery {
                                igt_ms,
                                grace_entity_id,
                                map_id,
                                position,
                                play_region_id,
                                message_id,
                            });
                        }
                        _ => {}
                    }
                    drained += 1;
                }
                if drained > 0 {
                    info!(count = drained, "[WS] Drained stale outgoing messages");
                }

                let _ =
                    incoming_tx.send(MachineMessage::StatusChanged(ConnectionStatus::Connected));
                reconnect_delay = Duration::from_secs(1);

                let result = message_loop(
                    &mut socket,
                    &outgoing_rx,
                    &incoming_tx,
                    &shutdown_flag,
                    &stop_reconnect,
                );
                if let Err(e) = &result {
                    info!(error = %e, "[WS] Disconnected");
                    last_disconnect_reason = Some(e.clone());
                }
                let _ = socket.close(None);

                if result.is_err() && !shutdown_flag.load(Ordering::SeqCst) {
                    let _ = incoming_tx.send(MachineMessage::StatusChanged(
                        ConnectionStatus::Reconnecting,
                    ));
                }
            }
            Err(e) => {
                consecutive_failures += 1;
                last_disconnect_reason = Some(e.clone());

                if e.starts_with("Auth failed:") {
                    // Auth rejection is permanent, do not reconnect
                    let _ = incoming_tx.send(MachineMessage::PermanentError(e.clone()));
                    let _ =
                        incoming_tx.send(MachineMessage::StatusChanged(ConnectionStatus::Error));
                    break;
                }

                error!(error = %e, attempts = consecutive_failures, "[WS] Connection failed");
                let _ = incoming_tx.send(MachineMessage::Error(e.clone()));
                let _ = incoming_tx.send(MachineMessage::StatusChanged(ConnectionStatus::Error));
            }
        }

        if shutdown_flag.load(Ordering::SeqCst) || stop_reconnect.load(Ordering::SeqCst) {
            break;
        }

        info!(
            delay_secs = reconnect_delay.as_secs(),
            failures = consecutive_failures,
            reason = last_disconnect_reason.as_deref().unwrap_or("unknown"),
            "[WS] Reconnecting..."
        );
        thread::sleep(reconnect_delay);
        reconnect_delay = (reconnect_delay * 2).min(max_delay);
    }

    let _ = incoming_tx.send(MachineMessage::StatusChanged(
        ConnectionStatus::Disconnected,
    ));
}

fn connect_and_auth(
    url: &str,
    mod_token: &str,
    incoming_tx: &Sender<MachineMessage>,
) -> Result<WebSocket<MaybeTlsStream<TcpStream>>, String> {
    let (mut socket, _) = connect(url).map_err(|e| format!("Connect failed: {}", e))?;

    // Send auth
    let auth = ClientMessage::Auth {
        mod_token: mod_token.to_string(),
        protocol_version: PROTOCOL_VERSION.to_string(),
        mod_version: env!("CARGO_PKG_VERSION").to_string(),
    };
    let json = serde_json::to_string(&auth).map_err(|e| format!("JSON: {}", e))?;
    socket
        .send(Message::Text(json))
        .map_err(|e| format!("Send: {}", e))?;

    // Wait for response
    let resp = socket.read().map_err(|e| format!("Read: {}", e))?;
    match resp {
        Message::Text(text) => {
            let msg: ServerMessage =
                serde_json::from_str(&text).map_err(|e| format!("Parse: {}", e))?;

            match msg {
                ServerMessage::AuthOk {
                    participant_id,
                    race,
                    seed,
                    participants,
                    phantom_skin,
                    latest_mod_version,
                } => {
                    let _ = incoming_tx.send(MachineMessage::AuthOk {
                        participant_id,
                        race: *race,
                        seed,
                        participants,
                        phantom_skin,
                        latest_mod_version,
                    });
                    Ok(socket)
                }
                ServerMessage::AuthError { message } => {
                    let _ = incoming_tx.send(MachineMessage::AuthError(message.clone()));
                    Err(format!("Auth failed: {}", message))
                }
                _ => Err(format!("Unexpected response: {:?}", msg)),
            }
        }
        Message::Close(frame) => {
            if let Some(ref cf) = frame {
                let code: u16 = cf.code.into();
                let reason = cf.reason.to_string();
                if is_permanent_close(code) {
                    let msg = if reason.is_empty() {
                        format!("Server rejected (code {})", code)
                    } else {
                        reason
                    };
                    let _ = incoming_tx.send(MachineMessage::PermanentError(msg));
                    return Err(format!("Auth failed: server closed (code={})", code));
                }
            }
            Err("Server closed during auth".to_string())
        }
        _ => Err("Unexpected message type".to_string()),
    }
}

fn message_loop(
    socket: &mut WebSocket<MaybeTlsStream<TcpStream>>,
    outgoing_rx: &Receiver<OutgoingMessage>,
    incoming_tx: &Sender<MachineMessage>,
    shutdown_flag: &Arc<AtomicBool>,
    stop_reconnect: &AtomicBool,
) -> Result<(), String> {
    let mut last_ping_received = Instant::now();
    let ping_timeout = Duration::from_secs(60);

    // Set non-blocking
    match socket.get_ref() {
        MaybeTlsStream::Plain(tcp) => {
            let _ = tcp.set_nonblocking(true);
        }
        MaybeTlsStream::NativeTls(tls) => {
            let _ = tls.get_ref().set_nonblocking(true);
        }
        _ => {}
    }

    loop {
        if shutdown_flag.load(Ordering::SeqCst) {
            return Ok(());
        }

        // Check ping timeout
        if last_ping_received.elapsed() > ping_timeout {
            return Err("Server ping timeout (60s)".to_string());
        }

        // Handle outgoing
        match outgoing_rx.try_recv() {
            Ok(OutgoingMessage::Ready) => {
                info!("[WS] Sending: ready");
                let msg = ClientMessage::Ready;
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::StatusUpdate {
                igt_ms,
                death_count,
                weapons,
            }) => {
                let msg = ClientMessage::StatusUpdate {
                    igt_ms,
                    death_count,
                    weapons,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::EventFlag {
                flag_id,
                igt_ms,
                message_id,
            }) => {
                info!(flag_id, igt_ms, message_id, "[WS] Sending: event_flag");
                let msg = ClientMessage::EventFlag {
                    flag_id,
                    igt_ms,
                    message_id,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::ZoneQuery {
                igt_ms,
                grace_entity_id,
                map_id,
                position,
                play_region_id,
                message_id,
            }) => {
                info!(
                    ?grace_entity_id,
                    ?map_id,
                    message_id,
                    "[WS] Sending: zone_query"
                );
                let msg = ClientMessage::ZoneQuery {
                    igt_ms,
                    grace_entity_id,
                    map_id,
                    position,
                    play_region_id,
                    message_id,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::Shutdown) => return Ok(()),
            Err(TryRecvError::Empty) => {}
            Err(TryRecvError::Disconnected) => return Err("Channel disconnected".to_string()),
        }

        // Handle incoming
        match socket.read() {
            Ok(Message::Text(text)) => {
                let parsed = serde_json::from_str::<ServerMessage>(&text);
                if let Err(ref e) = parsed {
                    warn!(error = %e, text_len = text.len(), "[WS] Failed to parse server message");
                }
                if let Ok(msg) = parsed {
                    match msg {
                        ServerMessage::Ping => {
                            last_ping_received = Instant::now();
                            let pong = ClientMessage::Pong;
                            let json = serde_json::to_string(&pong).map_err(|e| e.to_string())?;
                            socket
                                .send(Message::Text(json))
                                .map_err(|e| e.to_string())?;
                        }
                        ServerMessage::RaceStart { countdown_seconds } => {
                            if incoming_tx
                                .send(MachineMessage::RaceStart(countdown_seconds))
                                .is_err()
                            {
                                warn!("[WS] Incoming channel full/closed: race_start dropped");
                            }
                        }
                        ServerMessage::LeaderboardUpdate {
                            participants,
                            leader_splits,
                        } => {
                            let _ = incoming_tx.send(MachineMessage::LeaderboardUpdate {
                                participants,
                                leader_splits: leader_splits.map(crate::core::parse_splits),
                            });
                        }
                        ServerMessage::RaceStatusChange { status } => {
                            if incoming_tx
                                .send(MachineMessage::RaceStatusChange {
                                    status,
                                    current_igt: None,
                                })
                                .is_err()
                            {
                                warn!(
                                    "[WS] Incoming channel full/closed: race_status_change dropped"
                                );
                            }
                        }
                        ServerMessage::RaceInfoUpdate { race } => {
                            if incoming_tx
                                .send(MachineMessage::RaceInfoUpdate(*race))
                                .is_err()
                            {
                                warn!(
                                    "[WS] Incoming channel full/closed: race_info_update dropped"
                                );
                            }
                        }
                        ServerMessage::PlayerUpdate { player } => {
                            let _ = incoming_tx.send(MachineMessage::PlayerUpdate(player));
                        }
                        ServerMessage::ZoneUpdate {
                            node_id,
                            display_name,
                            tier,
                            original_tier,
                            layer,
                            is_first_visit,
                            exits,
                            message_id,
                        } => {
                            if incoming_tx
                                .send(MachineMessage::ZoneUpdate {
                                    node_id,
                                    display_name,
                                    tier,
                                    original_tier,
                                    layer,
                                    is_first_visit,
                                    exits,
                                    message_id,
                                })
                                .is_err()
                            {
                                warn!("[WS] Incoming channel full/closed: zone_update dropped");
                            }
                        }
                        ServerMessage::EventFlagAck { message_id } => {
                            let _ = incoming_tx.send(MachineMessage::EventFlagAck { message_id });
                        }
                        ServerMessage::ZoneQueryAck { message_id } => {
                            let _ = incoming_tx.send(MachineMessage::ZoneQueryAck { message_id });
                        }
                        ServerMessage::DeathCounts { counts } => {
                            let _ = incoming_tx.send(MachineMessage::DeathCounts(counts));
                        }
                        ServerMessage::Error { message } => {
                            if incoming_tx.send(MachineMessage::Error(message)).is_err() {
                                warn!("[WS] Incoming channel full/closed: error dropped");
                            }
                        }
                        _ => {}
                    }
                }
            }
            Ok(Message::Close(frame)) => {
                if let Some(ref cf) = frame {
                    let code: u16 = cf.code.into();
                    let reason = cf.reason.to_string();
                    if is_permanent_close(code) {
                        stop_reconnect.store(true, Ordering::SeqCst);
                        let msg = if reason.is_empty() {
                            format!("Server rejected (code {})", code)
                        } else {
                            reason.clone()
                        };
                        let _ = incoming_tx.send(MachineMessage::PermanentError(msg));
                    }
                    return Err(format!(
                        "Server closed (code={}, reason={})",
                        code, cf.reason
                    ));
                }
                return Err("Server closed".to_string());
            }
            Err(tungstenite::Error::Io(ref e))
                if e.kind() == std::io::ErrorKind::WouldBlock
                    || e.kind() == std::io::ErrorKind::Interrupted => {}
            Err(e) => return Err(format!("Read error: {}", e)),
            _ => {}
        }

        thread::sleep(Duration::from_millis(10));
    }
}
