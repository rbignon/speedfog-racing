//! Formatting utilities for race data display.

use std::collections::HashMap;
use std::fmt::Write;

use crate::core::protocol::ParticipantStatus;

/// Convert a `HashMap<String, i32>` (JSON wire format) to `HashMap<i32, i32>`.
/// Keys that fail to parse are silently dropped.
pub fn parse_splits(src: HashMap<String, i32>) -> HashMap<i32, i32> {
    src.into_iter()
        .filter_map(|(k, v)| k.parse::<i32>().ok().map(|k| (k, v)))
        .collect()
}

/// Write a signed millisecond value as `M:SS` / `H:MM:SS`, or `--:--` when negative.
pub fn format_time_into(buf: &mut String, ms: i32) {
    if ms < 0 {
        buf.push_str("--:--");
        return;
    }
    let ms = ms as u32;
    let secs = ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    if hours > 0 {
        write!(buf, "{}:{:02}:{:02}", hours, mins % 60, secs % 60).ok();
    } else {
        write!(buf, "{:02}:{:02}", mins, secs % 60).ok();
    }
}

/// Write the right-column text for a participant into an existing buffer.
///
/// Returns the finish time for `finished`, layer progress (`N/total`) for
/// `playing`, and the raw status label for any other state (registered,
/// ready, abandoned). Keeps pre-launch states visible once the race is
/// running so "ready" doesn't silently become `1/LAYERS`.
pub fn write_participant_right_text(
    buf: &mut String,
    status: ParticipantStatus,
    current_layer: i32,
    total_layers: i32,
    igt_ms: i32,
) {
    match status {
        ParticipantStatus::Finished => format_time_into(buf, igt_ms),
        ParticipantStatus::Playing => {
            let display = (current_layer + 1).min(total_layers);
            write!(buf, "{}/{}", display, total_layers).ok();
        }
        _ => buf.push_str(status.as_str()),
    }
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
// The eight parameters are all distinct gap-calc inputs; bundling them into a
// struct would not read more clearly than the positional arguments here.
#[allow(clippy::too_many_arguments)]
pub fn compute_gap(
    igt_ms: i32,
    current_layer: i32,
    layer_entry_igt: Option<i32>,
    leader_splits: &HashMap<i32, i32>,
    is_leader: bool,
    status: ParticipantStatus,
    leader_igt_ms: i32,
    leader_finished: bool,
) -> Option<i32> {
    if is_leader {
        return None;
    }
    match status {
        ParticipantStatus::Finished => Some(igt_ms - leader_igt_ms),
        ParticipantStatus::Playing => {
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

/// How a ranked leaderboard of `n` entries should be displayed when only a
/// limited number of rows fit, given the local player's 0-based rank `my_index`.
#[derive(Debug, PartialEq, Eq)]
pub struct LeaderboardLayout {
    /// Anchor the local row: show the top 9, a "…" separator, then the local
    /// player's own row (used when the local player ranks outside the top 10).
    pub need_anchor: bool,
    /// Number of top-ranked rows to render before any anchor.
    pub top_count: usize,
    /// Count for the "+ N more" footer. When anchored this is the number of
    /// players ranked *below* the local row, so it answers "how many are behind
    /// me"; the "…" already stands in for those ranked between the top and the
    /// local row. Without an anchor it is every participant past the rendered
    /// rows.
    pub footer_more: usize,
}

/// Compute the display layout for a leaderboard of `n` entries.
///
/// `my_index` is the local player's 0-based rank, or `None` when there is no
/// local player (e.g. a spectator).
pub fn compute_leaderboard_layout(n: usize, my_index: Option<usize>) -> LeaderboardLayout {
    match my_index {
        // Local player ranks outside the top 10: show the top 9, a "…", then
        // the local row; the footer counts only the players ranked below it.
        Some(idx) if n > 10 && idx >= 10 => LeaderboardLayout {
            need_anchor: true,
            top_count: 9,
            footer_more: n.saturating_sub(idx + 1),
        },
        // Everyone ranks within (or fits inside) the top 10: plain view, the
        // footer counts whoever is left past the rendered rows.
        _ => {
            let top_count = 10.min(n);
            LeaderboardLayout {
                need_anchor: false,
                top_count,
                footer_more: n.saturating_sub(top_count),
            }
        }
    }
}

/// Whether the player's loaded seed pack is stale relative to the server.
///
/// `config_seed_id` is the seed id of the pack the player loaded (empty when
/// none is configured); `server_seed_id` is the race's current seed id, when
/// the server reports one. Stale means the player has a configured pack and the
/// server's seed differs, e.g. after a reroll.
pub fn is_seed_stale(config_seed_id: &str, server_seed_id: Option<&str>) -> bool {
    !config_seed_id.is_empty() && server_seed_id.is_some_and(|s| s != config_seed_id)
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
        let gap = compute_gap(
            100000,
            2,
            Some(80000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 80000, leader at 75000 -> entry_delta = 5000
        // Leader spent 45000 in layer (120000-75000), player spent 50000 (130000-80000)
        // Layer overshoot = 50000 - 45000 = 5000
        // gap = 5000 + 5000 = 10000
        let gap = compute_gap(
            130000,
            2,
            Some(80000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, Some(10000));
    }

    #[test]
    fn test_compute_gap_exceeded_budget_ahead_player() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 70000, leader at 75000 -> entry_delta = -5000
        // Leader spent 45000 in layer, player spent 55000 (125000-70000)
        // Layer overshoot = 55000 - 45000 = 10000
        // gap = -5000 + 10000 = 5000
        let gap = compute_gap(
            125000,
            2,
            Some(70000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, Some(5000));
    }

    #[test]
    fn test_compute_gap_negative_ahead() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Player entered layer 2 at 70000 (ahead of leader at 75000)
        let gap = compute_gap(
            80000,
            2,
            Some(70000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, Some(-5000));
    }

    #[test]
    fn test_compute_gap_leader_on_same_layer() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000)]);
        // No layer 3 split -> leader still on layer 2
        let gap = compute_gap(
            90000,
            2,
            Some(80000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, Some(5000)); // entry delta only
    }

    #[test]
    fn test_compute_gap_finished() {
        let splits = HashMap::new();
        let gap = compute_gap(
            150000,
            3,
            None,
            &splits,
            false,
            ParticipantStatus::Finished,
            120000,
            true,
        );
        assert_eq!(gap, Some(30000));
    }

    #[test]
    fn test_compute_gap_leader_none() {
        let splits = HashMap::new();
        let gap = compute_gap(
            100000,
            2,
            Some(80000),
            &splits,
            true,
            ParticipantStatus::Playing,
            0,
            false,
        );
        assert_eq!(gap, None);
    }

    #[test]
    fn test_compute_gap_ready_none() {
        let splits = HashMap::new();
        let gap = compute_gap(
            0,
            0,
            None,
            &splits,
            false,
            ParticipantStatus::Ready,
            0,
            false,
        );
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
            ParticipantStatus::Playing,
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
            ParticipantStatus::Playing,
            150000,
            true,
        );
        assert_eq!(gap, Some(15000));
    }

    #[test]
    fn test_compute_gap_last_layer_leader_not_finished() {
        // Last layer (3), leader NOT finished yet -> entry delta only
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        let gap = compute_gap(
            165000,
            3,
            Some(125000),
            &splits,
            false,
            ParticipantStatus::Playing,
            0,
            false,
        );
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

    #[test]
    fn test_format_time_negative_is_placeholder() {
        let mut buf = String::new();
        format_time_into(&mut buf, -1);
        assert_eq!(buf, "--:--");
    }

    #[test]
    fn test_format_time_seconds_and_minutes() {
        let mut buf = String::new();
        format_time_into(&mut buf, 65_000);
        assert_eq!(buf, "01:05");
    }

    #[test]
    fn test_format_time_hours() {
        let mut buf = String::new();
        format_time_into(&mut buf, 3_723_000);
        assert_eq!(buf, "1:02:03");
    }

    #[test]
    fn test_right_text_finished_shows_time() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Finished, 5, 5, 125_000);
        assert_eq!(buf, "02:05");
    }

    #[test]
    fn test_right_text_playing_shows_layer_progress() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Playing, 0, 5, 1_000);
        assert_eq!(buf, "1/5");
    }

    #[test]
    fn test_right_text_playing_caps_at_total() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Playing, 10, 5, 1_000);
        assert_eq!(buf, "5/5");
    }

    #[test]
    fn test_right_text_ready_shows_status_label() {
        // Even when the race is running (non-zero layer), a ready player
        // must keep showing the "ready" label instead of a misleading "1/LAYERS".
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Ready, 0, 5, 0);
        assert_eq!(buf, "ready");
    }

    #[test]
    fn test_right_text_registered_shows_status_label() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Registered, 0, 5, 0);
        assert_eq!(buf, "registered");
    }

    #[test]
    fn test_right_text_abandoned_shows_status_label() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Abandoned, 2, 5, 45_000);
        assert_eq!(buf, "abandoned");
    }

    #[test]
    fn test_layout_anchor_footer_counts_only_players_below() {
        // 20 players, local is 15th (index 14): board shows top 9, "…", then
        // our anchored row, so "+ N more" must report the 5 players ranked
        // behind us, not all 10 rows that are hidden.
        let layout = compute_leaderboard_layout(20, Some(14));
        assert!(layout.need_anchor);
        assert_eq!(layout.top_count, 9);
        assert_eq!(layout.footer_more, 5);
    }

    #[test]
    fn test_layout_anchor_last_place_has_no_footer() {
        // Local player is dead last: nobody is behind, so no "+ N more".
        let layout = compute_leaderboard_layout(20, Some(19));
        assert!(layout.need_anchor);
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_layout_anchor_threshold() {
        // Smallest field that triggers an anchor: 11 players, local is last
        // (index 10). Top 9 + "…" + self = 10 rows, nobody ranked behind.
        let layout = compute_leaderboard_layout(11, Some(10));
        assert!(layout.need_anchor);
        assert_eq!(layout.top_count, 9);
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_layout_no_anchor_counts_hidden_tail() {
        // Local player ranks inside the top 10 (index 3): plain top-10 view, so
        // the footer counts everyone past row 10.
        let layout = compute_leaderboard_layout(20, Some(3));
        assert!(!layout.need_anchor);
        assert_eq!(layout.top_count, 10);
        assert_eq!(layout.footer_more, 10);
    }

    #[test]
    fn test_layout_spectator_no_anchor() {
        // No local player (spectator): never anchor, footer is the hidden tail.
        let layout = compute_leaderboard_layout(20, None);
        assert!(!layout.need_anchor);
        assert_eq!(layout.top_count, 10);
        assert_eq!(layout.footer_more, 10);
    }

    #[test]
    fn test_layout_small_field_fits_without_footer() {
        // Eight players, all fit: no anchor, no footer.
        let layout = compute_leaderboard_layout(8, Some(6));
        assert!(!layout.need_anchor);
        assert_eq!(layout.top_count, 8);
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_seed_stale_when_server_differs() {
        assert!(is_seed_stale("pack-abc", Some("server-xyz")));
    }

    #[test]
    fn test_seed_not_stale_when_server_matches() {
        assert!(!is_seed_stale("pack-abc", Some("pack-abc")));
    }

    #[test]
    fn test_seed_not_stale_when_config_empty() {
        // No configured pack: nothing to be stale against, even if the server
        // reports a seed.
        assert!(!is_seed_stale("", Some("server-xyz")));
    }

    #[test]
    fn test_seed_not_stale_when_server_unknown() {
        // No server seed_id in the payload: leave the player alone.
        assert!(!is_seed_stale("pack-abc", None));
    }
}
