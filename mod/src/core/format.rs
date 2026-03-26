//! Formatting utilities for race data display.

use std::collections::HashMap;
use std::fmt::Write;

/// Format a gap in milliseconds as `+M:SS` / `+H:MM:SS` (behind)
/// or `-M:SS` / `-H:MM:SS` (ahead).
pub fn format_gap(ms: i32) -> String {
    let mut buf = String::with_capacity(10);
    format_gap_into(&mut buf, ms);
    buf
}

/// Write a gap into an existing buffer (avoids allocation when reused).
pub fn format_gap_into(buf: &mut String, ms: i32) {
    let (sign, abs_ms) = if ms < 0 {
        ("-", (-ms) as u32)
    } else {
        ("+", ms as u32)
    };
    let secs = abs_ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    if hours > 0 {
        write!(buf, "{}{}:{:02}:{:02}", sign, hours, mins % 60, secs % 60).ok();
    } else {
        write!(buf, "{}{}:{:02}", sign, mins, secs % 60).ok();
    }
}

/// Compute LiveSplit-style gap for a single participant.
///
/// Returns `None` for leader, non-playing statuses, or missing splits.
/// Uses the caller's `igt_ms` (local IGT for self, server snapshot for others).
pub fn compute_gap(
    igt_ms: i32,
    current_layer: i32,
    layer_entry_igt: Option<i32>,
    leader_splits: &HashMap<String, i32>,
    is_leader: bool,
    status: &str,
    leader_igt_ms: i32,
) -> Option<i32> {
    if is_leader {
        return None;
    }
    match status {
        "finished" => Some(igt_ms - leader_igt_ms),
        "playing" => {
            let layer_key = current_layer.to_string();
            let leader_entry = leader_splits.get(&layer_key)?;
            let player_entry = layer_entry_igt?;
            let entry_delta = player_entry - leader_entry;
            // Leader's exit = leader's entry on next layer
            let next_key = (current_layer + 1).to_string();
            let leader_exit = leader_splits.get(&next_key);
            match leader_exit {
                None => Some(entry_delta),
                Some(&exit_igt) => {
                    // Compare time spent in layer, not absolute IGTs
                    let time_in_layer = igt_ms - player_entry;
                    let leader_time_in_layer = exit_igt - leader_entry;
                    if time_in_layer <= leader_time_in_layer {
                        Some(entry_delta)
                    } else {
                        Some(entry_delta + (time_in_layer - leader_time_in_layer))
                    }
                }
            }
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_gap_seconds() {
        assert_eq!(format_gap(5000), "+0:05");
    }

    #[test]
    fn test_format_gap_minutes() {
        assert_eq!(format_gap(135000), "+2:15");
    }

    #[test]
    fn test_format_gap_hours() {
        assert_eq!(format_gap(3_723_000), "+1:02:03");
    }

    #[test]
    fn test_format_gap_zero() {
        assert_eq!(format_gap(0), "+0:00");
    }

    #[test]
    fn test_format_gap_negative() {
        assert_eq!(format_gap(-5000), "-0:05");
    }

    #[test]
    fn test_format_gap_negative_minutes() {
        assert_eq!(format_gap(-135000), "-2:15");
    }

    #[test]
    fn test_compute_gap_within_budget() {
        let splits = HashMap::from([
            ("0".into(), 0),
            ("1".into(), 30000),
            ("2".into(), 75000),
            ("3".into(), 120000),
        ]);
        // Player entered layer 2 at 80000, leader at 75000
        // Current IGT 100000 < leader exit 120000 → entry delta
        let gap = compute_gap(100000, 2, Some(80000), &splits, false, "playing", 0);
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget() {
        let splits = HashMap::from([
            ("0".into(), 0),
            ("1".into(), 30000),
            ("2".into(), 75000),
            ("3".into(), 120000),
        ]);
        // Player entered layer 2 at 80000, leader at 75000 -> entry_delta = 5000
        // Leader spent 45000 in layer (120000-75000), player spent 50000 (130000-80000)
        // Layer overshoot = 50000 - 45000 = 5000
        // gap = 5000 + 5000 = 10000
        let gap = compute_gap(130000, 2, Some(80000), &splits, false, "playing", 0);
        assert_eq!(gap, Some(10000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget_ahead_player() {
        let splits = HashMap::from([
            ("0".into(), 0),
            ("1".into(), 30000),
            ("2".into(), 75000),
            ("3".into(), 120000),
        ]);
        // Player entered layer 2 at 70000, leader at 75000 -> entry_delta = -5000
        // Leader spent 45000 in layer, player spent 55000 (125000-70000)
        // Layer overshoot = 55000 - 45000 = 10000
        // gap = -5000 + 10000 = 5000
        let gap = compute_gap(125000, 2, Some(70000), &splits, false, "playing", 0);
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_negative_ahead() {
        let splits = HashMap::from([
            ("0".into(), 0),
            ("1".into(), 30000),
            ("2".into(), 75000),
            ("3".into(), 120000),
        ]);
        // Player entered layer 2 at 70000 (ahead of leader at 75000)
        let gap = compute_gap(80000, 2, Some(70000), &splits, false, "playing", 0);
        assert_eq!(gap, Some(-5000));
    }

    #[test]
    fn test_compute_gap_leader_on_same_layer() {
        let splits = HashMap::from([("0".into(), 0), ("1".into(), 30000), ("2".into(), 75000)]);
        // No layer 3 split → leader still on layer 2
        let gap = compute_gap(90000, 2, Some(80000), &splits, false, "playing", 0);
        assert_eq!(gap, Some(5000)); // entry delta only
    }

    #[test]
    fn test_compute_gap_finished() {
        let splits = HashMap::new();
        let gap = compute_gap(150000, 3, None, &splits, false, "finished", 120000);
        assert_eq!(gap, Some(30000));
    }

    #[test]
    fn test_compute_gap_leader_none() {
        let splits = HashMap::new();
        let gap = compute_gap(100000, 2, Some(80000), &splits, true, "playing", 0);
        assert_eq!(gap, None);
    }

    #[test]
    fn test_compute_gap_ready_none() {
        let splits = HashMap::new();
        let gap = compute_gap(0, 0, None, &splits, false, "ready", 0);
        assert_eq!(gap, None);
    }
}
