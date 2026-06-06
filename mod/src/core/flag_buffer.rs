//! Event flag buffering across loading screens and disconnections.
//!
//! Flags go through two stages:
//! - **deferred**: detected by 10Hz polling, waiting for loading screen exit to send
//! - **pending**: waiting for server reconnection to re-send
//!
//! Normal flow: poll detects flag -> deferred -> loading exit -> send to server
//! Disconnected flow: poll detects flag -> deferred -> loading exit -> park to pending
//!                    -> reconnect -> drain pending -> send to server
//!
//! Also exposes `detect_save_reload`, used by the tracker to flush per-save
//! event-flag state (the buffers above plus `triggered_flags`) when the player
//! loads a different save mid-session.

/// Minimum IGT regression (ms) treated as a save reload. Elden Ring's IGT is
/// monotonic within a save, so any meaningful decrease means the player loaded
/// a different save. The margin absorbs read jitter without missing the
/// stale-save -> fresh-save transition (which goes from minutes to ~0).
pub const SAVE_RELOAD_IGT_DROP_MS: u32 = 1_000;

/// Returns true when `current` is a meaningful regression from `prev`,
/// indicating the player loaded a different save since the last observation.
/// `None` for `prev` means no prior reading (first observation in session).
pub fn detect_save_reload(prev: Option<u32>, current: u32) -> bool {
    match prev {
        Some(p) => current + SAVE_RELOAD_IGT_DROP_MS <= p,
        None => false,
    }
}

/// Manages event flag buffering across loading screens and disconnections.
#[derive(Debug, Default)]
pub struct FlagBuffer {
    /// Flags detected this loading cycle, sent at loading exit
    deferred: Vec<(u32, u32)>,
    /// Flags buffered during disconnection, sent on reconnect
    pending: Vec<(u32, u32)>,
}

impl FlagBuffer {
    /// Defer a flag for sending at loading screen exit.
    ///
    /// Deduplicates by flag_id: if the same flag was already deferred in this
    /// loading cycle, the first occurrence wins (more accurate IGT from the
    /// 10Hz poll during fade-out vs the rescan at loading exit).
    pub fn defer(&mut self, flag_id: u32, igt_ms: u32) {
        if !self.deferred.iter().any(|(fid, _)| *fid == flag_id) {
            self.deferred.push((flag_id, igt_ms));
        }
    }

    pub fn has_deferred(&self) -> bool {
        !self.deferred.is_empty()
    }

    pub fn drain_deferred(&mut self) -> std::vec::Drain<'_, (u32, u32)> {
        self.deferred.drain(..)
    }

    /// Move deferred flags to pending for later re-send on reconnect.
    /// Returns the number of flags moved.
    pub fn park_deferred(&mut self) -> usize {
        let count = self.deferred.len();
        self.pending.append(&mut self.deferred);
        count
    }

    pub fn clear_deferred(&mut self) {
        self.deferred.clear();
    }

    pub fn add_pending(&mut self, flag_id: u32, igt_ms: u32) {
        self.pending.push((flag_id, igt_ms));
    }

    pub fn drain_pending(&mut self) -> std::vec::Drain<'_, (u32, u32)> {
        self.pending.drain(..)
    }

    pub fn clear_pending(&mut self) {
        self.pending.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::{detect_save_reload, FlagBuffer};

    #[test]
    fn detect_save_reload_returns_false_without_prior_reading() {
        assert!(!detect_save_reload(None, 0));
        assert!(!detect_save_reload(None, 10_000_000));
    }

    #[test]
    fn detect_save_reload_returns_false_for_monotonic_igt() {
        assert!(!detect_save_reload(Some(0), 0));
        assert!(!detect_save_reload(Some(1000), 1100));
        assert!(!detect_save_reload(Some(1_000_000), 2_000_000));
    }

    #[test]
    fn detect_save_reload_ignores_jitter_below_threshold() {
        // A reading slightly lower than the previous (jitter, not a real reload).
        assert!(!detect_save_reload(Some(5_000), 4_500));
        assert!(!detect_save_reload(Some(5_000), 4_001));
    }

    #[test]
    fn detect_save_reload_fires_on_stale_to_fresh_transition() {
        // Player loads a stale save (IGT ~141 min) then starts a fresh game (IGT 0).
        assert!(detect_save_reload(Some(8_491_593), 0));
        assert!(detect_save_reload(Some(60_000), 0));
        // Boundary: drop of exactly SAVE_RELOAD_IGT_DROP_MS counts as a reload.
        assert!(detect_save_reload(Some(5_000), 4_000));
    }

    #[test]
    fn park_deferred_moves_to_pending() {
        let mut buf = FlagBuffer::default();
        buf.defer(100, 1000);
        buf.defer(101, 1100);
        buf.defer(102, 1200);

        let count = buf.park_deferred();

        assert_eq!(count, 3);
        assert!(!buf.has_deferred());
        let pending: Vec<_> = buf.drain_pending().collect();
        assert_eq!(pending, vec![(100, 1000), (101, 1100), (102, 1200)]);
    }

    #[test]
    fn park_deferred_empty_is_noop() {
        let mut buf = FlagBuffer::default();
        let count = buf.park_deferred();
        assert_eq!(count, 0);
        assert!(buf.drain_pending().next().is_none());
    }

    #[test]
    fn clear_deferred_discards_without_affecting_pending() {
        let mut buf = FlagBuffer::default();
        buf.add_pending(200, 5000);
        buf.defer(100, 1000);

        buf.clear_deferred();

        assert!(!buf.has_deferred());
        let pending: Vec<_> = buf.drain_pending().collect();
        assert_eq!(pending, vec![(200, 5000)]);
    }

    #[test]
    fn drain_pending_after_park_and_requeue() {
        let mut buf = FlagBuffer::default();
        // Fog gate detected while disconnected, parked at loading exit
        buf.defer(100, 1000);
        buf.park_deferred();
        // WS channel had a flag that was never sent, re-queued
        buf.add_pending(200, 5000);

        let pending: Vec<_> = buf.drain_pending().collect();
        assert_eq!(pending, vec![(100, 1000), (200, 5000)]);
        assert!(buf.drain_pending().next().is_none());
    }

    #[test]
    fn multiple_loading_exits_while_disconnected_accumulate() {
        let mut buf = FlagBuffer::default();
        // First loading cycle
        buf.defer(100, 1000);
        buf.park_deferred();
        // Second loading cycle (player traversed another fog gate)
        buf.defer(101, 2000);
        buf.park_deferred();

        let pending: Vec<_> = buf.drain_pending().collect();
        assert_eq!(pending, vec![(100, 1000), (101, 2000)]);
    }

    #[test]
    fn drain_deferred_empties_buffer() {
        let mut buf = FlagBuffer::default();
        buf.defer(100, 1000);
        buf.defer(101, 1100);

        let sent: Vec<_> = buf.drain_deferred().collect();
        assert_eq!(sent, vec![(100, 1000), (101, 1100)]);
        assert!(!buf.has_deferred());
    }

    #[test]
    fn clear_pending_discards_without_affecting_deferred() {
        let mut buf = FlagBuffer::default();
        buf.defer(100, 1000);
        buf.add_pending(200, 5000);

        buf.clear_pending();

        assert!(buf.drain_pending().next().is_none());
        let deferred: Vec<_> = buf.drain_deferred().collect();
        assert_eq!(deferred, vec![(100, 1000)]);
    }

    #[test]
    fn defer_deduplicates_by_flag_id() {
        let mut buf = FlagBuffer::default();
        buf.defer(100, 1000);
        buf.defer(100, 1500); // same flag, different igt

        let sent: Vec<_> = buf.drain_deferred().collect();
        assert_eq!(sent, vec![(100, 1000)]); // keeps first occurrence
    }
}
