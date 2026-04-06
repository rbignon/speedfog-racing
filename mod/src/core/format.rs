//! Formatting utilities for race data display.

use std::collections::HashMap;
use std::fmt::Write;

/// Convert a `HashMap<String, i32>` (JSON wire format) to `HashMap<i32, i32>`.
/// Keys that fail to parse are silently dropped.
pub fn parse_splits(src: HashMap<String, i32>) -> HashMap<i32, i32> {
    src.into_iter()
        .filter_map(|(k, v)| k.parse::<i32>().ok().map(|k| (k, v)))
        .collect()
}

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
    leader_splits: &HashMap<i32, i32>,
    is_leader: bool,
    status: &str,
    leader_igt_ms: i32,
    leader_finished: bool,
) -> Option<i32> {
    if is_leader {
        return None;
    }
    match status {
        "finished" => Some(igt_ms - leader_igt_ms),
        "playing" => {
            let leader_entry = leader_splits.get(&current_layer)?;
            let player_entry = layer_entry_igt?;
            let entry_delta = player_entry - leader_entry;
            // Leader's exit = leader's entry on next layer
            let next_layer = current_layer + 1;
            let leader_exit = match leader_splits.get(&next_layer) {
                Some(&exit_igt) => exit_igt,
                None if leader_finished => leader_igt_ms,
                None => return Some(entry_delta),
            };
            // Compare time spent in layer, not absolute IGTs
            let time_in_layer = igt_ms - player_entry;
            let leader_time_in_layer = leader_exit - leader_entry;
            if time_in_layer <= leader_time_in_layer {
                Some(entry_delta)
            } else {
                Some(entry_delta + (time_in_layer - leader_time_in_layer))
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
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 80000, leader at 75000
        // Current IGT 100000 < leader exit 120000 -> entry delta
        let gap = compute_gap(100000, 2, Some(80000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 80000, leader at 75000 -> entry_delta = 5000
        // Leader spent 45000 in layer (120000-75000), player spent 50000 (130000-80000)
        // Layer overshoot = 50000 - 45000 = 5000
        // gap = 5000 + 5000 = 10000
        let gap = compute_gap(130000, 2, Some(80000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(10000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget_ahead_player() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 70000, leader at 75000 -> entry_delta = -5000
        // Leader spent 45000 in layer, player spent 55000 (125000-70000)
        // Layer overshoot = 55000 - 45000 = 10000
        // gap = -5000 + 10000 = 5000
        let gap = compute_gap(125000, 2, Some(70000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_negative_ahead() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 70000 (ahead of leader at 75000)
        let gap = compute_gap(80000, 2, Some(70000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(-5000));
    }

    #[test]
    fn test_compute_gap_leader_on_same_layer() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000)]);
        // No layer 3 split -> leader still on layer 2
        let gap = compute_gap(90000, 2, Some(80000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(5000)); // entry delta only
    }

    #[test]
    fn test_compute_gap_finished() {
        let splits = HashMap::new();
        let gap = compute_gap(150000, 3, None, &splits, false, "finished", 120000, true);
        assert_eq!(gap, Some(30000));
    }

    #[test]
    fn test_compute_gap_leader_none() {
        let splits = HashMap::new();
        let gap = compute_gap(100000, 2, Some(80000), &splits, true, "playing", 0, false);
        assert_eq!(gap, None);
    }

    #[test]
    fn test_compute_gap_ready_none() {
        let splits = HashMap::new();
        let gap = compute_gap(0, 0, None, &splits, false, "ready", 0, false);
        assert_eq!(gap, None);
    }

    #[test]
    fn test_compute_gap_last_layer_leader_finished_within_budget() {
        // Last layer (3), leader finished at 150000, no layer 4 split
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 3 at 125000, leader at 120000 -> entry_delta = 5000
        // Leader spent 30000 in layer (150000-120000), player spent 10000 (135000-125000)
        // Within budget -> entry delta only
        let gap = compute_gap(
            135000,
            3,
            Some(125000),
            &splits,
            false,
            "playing",
            150000,
            true,
        );
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_last_layer_leader_finished_exceeded() {
        // Last layer (3), leader finished at 150000, no layer 4 split
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 3 at 125000, leader at 120000 -> entry_delta = 5000
        // Leader spent 30000 in layer (150000-120000), player spent 40000 (165000-125000)
        // Overshoot = 40000 - 30000 = 10000
        // gap = 5000 + 10000 = 15000
        let gap = compute_gap(
            165000,
            3,
            Some(125000),
            &splits,
            false,
            "playing",
            150000,
            true,
        );
        assert_eq!(gap, Some(15000));
    }

    #[test]
    fn test_compute_gap_last_layer_leader_not_finished() {
        // Last layer (3), leader NOT finished yet -> entry delta only
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        let gap = compute_gap(165000, 3, Some(125000), &splits, false, "playing", 0, false);
        assert_eq!(gap, Some(5000)); // entry delta only
    }

    #[test]
    fn test_parse_splits() {
        let src = HashMap::from([
            ("0".to_string(), 0),
            ("1".to_string(), 30000),
            ("bad".to_string(), 999),
        ]);
        let parsed = parse_splits(src);
        assert_eq!(parsed.get(&0), Some(&0));
        assert_eq!(parsed.get(&1), Some(&30000));
        assert_eq!(parsed.len(), 2); // "bad" key dropped
    }
}
