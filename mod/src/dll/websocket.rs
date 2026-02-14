//! WebSocket client for SpeedFog Racing server
//!
//! Handles connection, authentication, and race message exchange.

use crossbeam_channel::{bounded, Receiver, Sender, TryRecvError};
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
    ClientMessage, ExitInfo, ParticipantInfo, RaceInfo, SeedInfo, ServerMessage,
};

// =============================================================================
// TYPES
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

/// Outgoing messages (main thread -> WS thread)
#[derive(Debug)]
pub enum OutgoingMessage {
    Ready,
    StatusUpdate { igt_ms: u32, death_count: u32 },
    EventFlag { flag_id: u32, igt_ms: u32 },
    Shutdown,
}

/// Incoming messages (WS thread -> main thread)
#[derive(Debug)]
pub enum IncomingMessage {
    StatusChanged(ConnectionStatus),
    AuthOk {
        participant_id: String,
        race: RaceInfo,
        seed: SeedInfo,
        participants: Vec<ParticipantInfo>,
    },
    AuthError(String),
    RaceStart,
    LeaderboardUpdate(Vec<ParticipantInfo>),
    RaceStatusChange(String),
    PlayerUpdate(ParticipantInfo),
    ZoneUpdate {
        node_id: String,
        display_name: String,
        tier: Option<i32>,
        exits: Vec<ExitInfo>,
    },
    /// Event flag drained from outgoing channel on reconnect — must be re-buffered
    RequeueEventFlag {
        flag_id: u32,
        igt_ms: u32,
    },
    Error(String),
}

// =============================================================================
// WEBSOCKET CLIENT
// =============================================================================

/// Thread-safe WebSocket client for racing server
pub struct RaceWebSocketClient {
    settings: ServerSettings,
    tx: Option<Sender<OutgoingMessage>>,
    rx: Option<Receiver<IncomingMessage>>,
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
        let (incoming_tx, incoming_rx) = bounded::<IncomingMessage>(128);

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
                let msg = if let Some(s) = panic_info.downcast_ref::<&str>() {
                    format!("WS thread panic: {}", s)
                } else {
                    "WS thread panic".to_string()
                };
                error!("{}", msg);
                let _ = incoming_tx.send(IncomingMessage::Error(msg));
                let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Error));
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

    pub fn send_status_update(&self, igt_ms: u32, death_count: u32) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::StatusUpdate {
                igt_ms,
                death_count,
            }) {
                warn!("[WS] Failed to queue message: {}", e);
            }
        }
    }

    pub fn send_event_flag(&self, flag_id: u32, igt_ms: u32) {
        if let Some(tx) = &self.tx {
            if let Err(e) = tx.try_send(OutgoingMessage::EventFlag { flag_id, igt_ms }) {
                warn!("[WS] Failed to queue message: {}", e);
            }
        }
    }

    pub fn poll(&mut self) -> Option<IncomingMessage> {
        let rx = self.rx.as_ref()?;
        match rx.try_recv() {
            Ok(msg) => {
                if let IncomingMessage::StatusChanged(status) = &msg {
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
    incoming_tx: Sender<IncomingMessage>,
    shutdown_flag: Arc<AtomicBool>,
) {
    let mut reconnect_delay = Duration::from_secs(1);
    let max_delay = Duration::from_secs(30);

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
        let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connecting));

        match connect_and_auth(&url, &settings.mod_token, &incoming_tx) {
            Ok(mut socket) => {
                info!("[WS] Connected and authenticated");

                // Drain stale outgoing messages before notifying Connected.
                // During disconnection, status_update messages pile up in the channel;
                // sending them before Ready would confuse the server.
                let mut drained = 0u32;
                while let Ok(msg) = outgoing_rx.try_recv() {
                    match msg {
                        OutgoingMessage::Shutdown => {
                            let _ = incoming_tx.send(IncomingMessage::StatusChanged(
                                ConnectionStatus::Disconnected,
                            ));
                            return;
                        }
                        OutgoingMessage::EventFlag { flag_id, igt_ms } => {
                            // Re-queue event flags back to the tracker for re-buffering.
                            // These were queued but never transmitted before disconnect.
                            let _ = incoming_tx
                                .send(IncomingMessage::RequeueEventFlag { flag_id, igt_ms });
                        }
                        _ => {}
                    }
                    drained += 1;
                }
                if drained > 0 {
                    info!(count = drained, "[WS] Drained stale outgoing messages");
                }

                let _ =
                    incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Connected));
                reconnect_delay = Duration::from_secs(1);

                let result = message_loop(&mut socket, &outgoing_rx, &incoming_tx, &shutdown_flag);
                if let Err(e) = &result {
                    info!(error = %e, "[WS] Disconnected");
                }
                let _ = socket.close(None);

                if result.is_err() && !shutdown_flag.load(Ordering::SeqCst) {
                    let _ = incoming_tx.send(IncomingMessage::StatusChanged(
                        ConnectionStatus::Reconnecting,
                    ));
                }
            }
            Err(e) => {
                error!(error = %e, "[WS] Connection failed");
                let _ = incoming_tx.send(IncomingMessage::Error(e.clone()));
                let _ = incoming_tx.send(IncomingMessage::StatusChanged(ConnectionStatus::Error));
            }
        }

        if shutdown_flag.load(Ordering::SeqCst) {
            break;
        }

        info!(delay = reconnect_delay.as_secs(), "[WS] Reconnecting...");
        thread::sleep(reconnect_delay);
        reconnect_delay = (reconnect_delay * 2).min(max_delay);
    }

    let _ = incoming_tx.send(IncomingMessage::StatusChanged(
        ConnectionStatus::Disconnected,
    ));
}

fn connect_and_auth(
    url: &str,
    mod_token: &str,
    incoming_tx: &Sender<IncomingMessage>,
) -> Result<WebSocket<MaybeTlsStream<TcpStream>>, String> {
    let (mut socket, _) = connect(url).map_err(|e| format!("Connect failed: {}", e))?;

    // Send auth
    let auth = ClientMessage::Auth {
        mod_token: mod_token.to_string(),
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
                } => {
                    let _ = incoming_tx.send(IncomingMessage::AuthOk {
                        participant_id,
                        race,
                        seed,
                        participants,
                    });
                    Ok(socket)
                }
                ServerMessage::AuthError { message } => {
                    let _ = incoming_tx.send(IncomingMessage::AuthError(message.clone()));
                    Err(format!("Auth failed: {}", message))
                }
                _ => Err(format!("Unexpected response: {:?}", msg)),
            }
        }
        _ => Err("Unexpected message type".to_string()),
    }
}

fn message_loop(
    socket: &mut WebSocket<MaybeTlsStream<TcpStream>>,
    outgoing_rx: &Receiver<OutgoingMessage>,
    incoming_tx: &Sender<IncomingMessage>,
    shutdown_flag: &Arc<AtomicBool>,
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
                let msg = ClientMessage::Ready;
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::StatusUpdate {
                igt_ms,
                death_count,
            }) => {
                let msg = ClientMessage::StatusUpdate {
                    igt_ms,
                    death_count,
                };
                let json = serde_json::to_string(&msg).map_err(|e| e.to_string())?;
                socket
                    .send(Message::Text(json))
                    .map_err(|e| e.to_string())?;
            }
            Ok(OutgoingMessage::EventFlag { flag_id, igt_ms }) => {
                let msg = ClientMessage::EventFlag { flag_id, igt_ms };
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
                if let Ok(msg) = serde_json::from_str::<ServerMessage>(&text) {
                    match msg {
                        ServerMessage::Ping => {
                            last_ping_received = Instant::now();
                            let pong = ClientMessage::Pong;
                            let json = serde_json::to_string(&pong).map_err(|e| e.to_string())?;
                            socket
                                .send(Message::Text(json))
                                .map_err(|e| e.to_string())?;
                        }
                        ServerMessage::RaceStart => {
                            let _ = incoming_tx.send(IncomingMessage::RaceStart);
                        }
                        ServerMessage::LeaderboardUpdate { participants } => {
                            let _ =
                                incoming_tx.send(IncomingMessage::LeaderboardUpdate(participants));
                        }
                        ServerMessage::RaceStatusChange { status } => {
                            let _ = incoming_tx.send(IncomingMessage::RaceStatusChange(status));
                        }
                        ServerMessage::PlayerUpdate { player } => {
                            let _ = incoming_tx.send(IncomingMessage::PlayerUpdate(player));
                        }
                        ServerMessage::ZoneUpdate {
                            node_id,
                            display_name,
                            tier,
                            exits,
                        } => {
                            let _ = incoming_tx.send(IncomingMessage::ZoneUpdate {
                                node_id,
                                display_name,
                                tier,
                                exits,
                            });
                        }
                        _ => {}
                    }
                }
            }
            Ok(Message::Close(_)) => return Err("Server closed".to_string()),
            Err(tungstenite::Error::Io(ref e)) if e.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(e) => return Err(format!("Read error: {}", e)),
            _ => {}
        }

        thread::sleep(Duration::from_millis(10));
    }
}
