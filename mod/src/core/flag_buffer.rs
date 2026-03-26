//! Event flag buffering across loading screens and disconnections.
//!
//! Flags go through two stages:
//! - **deferred**: detected by 10Hz polling, waiting for loading screen exit to send
//! - **pending**: waiting for server reconnection to re-send
//!
//! Normal flow: poll detects flag -> deferred -> loading exit -> send to server
//! Disconnected flow: poll detects flag -> deferred -> loading exit -> park to pending
//!                    -> reconnect -> drain pending -> send to server

/// Manages event flag buffering across loading screens and disconnections.
#[derive(Debug, Default)]
pub struct FlagBuffer {
    /// Flags detected this loading cycle, sent at loading exit
    deferred: Vec<(u32, u32)>,
    /// Flags buffered during disconnection, sent on reconnect
    pending: Vec<(u32, u32)>,
}

impl FlagBuffer {
    pub fn defer(&mut self, flag_id: u32, igt_ms: u32) {
        self.deferred.push((flag_id, igt_ms));
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
        self.pending.extend(self.deferred.drain(..));
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
}

#[cfg(test)]
mod tests {
    use super::FlagBuffer;

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
}
