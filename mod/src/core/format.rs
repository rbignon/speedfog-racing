//! Formatting utilities for race data display.

use std::collections::HashMap;
use std::fmt::Write;
use std::ops::Range;

use serde::{Deserialize, Serialize};

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
/// `playing`, "dead" for a deathless elimination (abandoned with at least
/// one death in a deathless race), and the raw status label for any other
/// state (registered, ready, abandoned). Keeps pre-launch states visible
/// once the race is running so "ready" doesn't silently become `1/LAYERS`.
pub fn write_participant_right_text(
    buf: &mut String,
    status: ParticipantStatus,
    current_layer: i32,
    total_layers: i32,
    igt_ms: i32,
    deathless: bool,
    death_count: i32,
) {
    match status {
        ParticipantStatus::Finished => format_time_into(buf, igt_ms),
        ParticipantStatus::Playing => {
            let display = (current_layer + 1).min(total_layers);
            write!(buf, "{}/{}", display, total_layers).ok();
        }
        ParticipantStatus::Abandoned if deathless && death_count > 0 => buf.push_str("dead"),
        ParticipantStatus::Disqualified => buf.push_str("DQ"),
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
/// Returns `None` for the leader, pre-race and disqualified statuses, or
/// missing splits. A DNF's gap is its arrival on its deepest layer against the
/// leader's, the time it ranks on.
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
        // Never the time spent there before abandoning, which would
        // contradict its rank. Everyone enters the start layer at 0, so a DNF
        // still there has no gap.
        ParticipantStatus::Abandoned if current_layer == 0 => None,
        ParticipantStatus::Abandoned => {
            let leader_entry = leader_splits.get(&current_layer)?;
            Some(layer_entry_igt? - leader_entry)
        }
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

/// Reference for the centered view's gaps: the local player's leader-relative
/// gap, or 0 when they lead (everyone's gap is then unchanged). `None` keeps
/// the board on leader-relative gaps: no leader yet, no local player
/// (spectator), or no gap of their own (disqualified, or abandoned on the
/// start layer).
pub fn player_gap_reference(
    my_index: Option<usize>,
    my_gap: Option<i32>,
    has_leader: bool,
) -> Option<i32> {
    match my_index {
        _ if !has_leader => None,
        Some(0) => Some(0),
        Some(_) => my_gap,
        None => None,
    }
}

/// A row's gap in the centered view: its leader-relative gap minus the
/// `reference` (see [`player_gap_reference`]), negative for runners ahead of
/// the local player and positive for those behind. The leader's row has no
/// leader-relative gap of its own but counts for 0 (`is_leader_row`); the
/// local row and rows without a gap show none.
pub fn gap_from_player(
    row_gap: Option<i32>,
    is_leader_row: bool,
    is_self: bool,
    reference: i32,
) -> Option<i32> {
    if is_self {
        return None;
    }
    let gap = if is_leader_row { Some(0) } else { row_gap };
    gap.map(|g| g - reference)
}

/// Which layout the in-game leaderboard uses when shown.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LeaderboardMode {
    /// Top 10, the local row anchored below the top 9 when ranked lower; gaps
    /// relative to the leader.
    Top,
    /// Top 3, then the local player with the three runners ahead and behind;
    /// gaps relative to the local player. Also what a layout this build does
    /// not know reads as, so a newer server's config still loads (hence last:
    /// serde's fallback variant).
    #[default]
    #[serde(other)]
    Centered,
}

impl LeaderboardMode {
    fn other(self) -> Self {
        match self {
            Self::Centered => Self::Top,
            Self::Top => Self::Centered,
        }
    }
}

/// What the leaderboard hotkey cycles through: hidden or one of the layouts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeaderboardView {
    Hidden,
    Shown(LeaderboardMode),
}

impl LeaderboardView {
    /// The view after a hotkey press: the configured `default` layout, then
    /// hidden, then the other layout, then the default again, so one press
    /// always hides the board from its starting view.
    pub fn next(self, default: LeaderboardMode) -> Self {
        match self {
            Self::Shown(mode) if mode == default => Self::Hidden,
            Self::Hidden => Self::Shown(default.other()),
            Self::Shown(_) => Self::Shown(default),
        }
    }
}

/// Rows of the plain view, and of the top block above the local player's own
/// rows in the top layout.
const LEADERBOARD_ROWS: usize = 10;
/// Rows of the top block in the centered layout.
const CENTERED_TOP_ROWS: usize = 3;
/// Runners shown on each side of the local player in the centered layout.
const CENTERED_NEIGHBOURS: usize = 3;
/// Lines the centered layout takes at most when split: the top block, the
/// "…", and the local player between their neighbours.
const CENTERED_SPLIT_LINES: usize = CENTERED_TOP_ROWS + 1 + 2 * CENTERED_NEIGHBOURS + 1;

/// How a ranked leaderboard of `n` entries should be displayed when only a
/// limited number of rows fit, given the local player's 0-based rank `my_index`.
#[derive(Debug, PartialEq, Eq)]
pub struct LeaderboardLayout {
    /// Number of top-ranked rows to render first.
    pub top_count: usize,
    /// Ranks rendered after a "…" separator, around the local player, when
    /// they are not contiguous with the top rows: the local row alone in the
    /// top layout, the local row and its neighbours in the centered layout.
    pub window: Option<Range<usize>>,
    /// Count for the "+ N more" footer: the players ranked below the last
    /// rendered row, so with a window it answers "how many are behind it";
    /// the "…" already stands in for those ranked between the top and the
    /// window.
    pub footer_more: usize,
}

/// Compute the display layout for a leaderboard of `n` entries.
///
/// `my_index` is the local player's 0-based rank, or `None` when there is no
/// local player (e.g. a spectator).
pub fn compute_leaderboard_layout(
    n: usize,
    my_index: Option<usize>,
    mode: LeaderboardMode,
) -> LeaderboardLayout {
    let plain = |rows: usize| {
        let top_count = rows.min(n);
        LeaderboardLayout {
            top_count,
            window: None,
            footer_more: n - top_count,
        }
    };
    let split = |top_count: usize, window: Range<usize>| LeaderboardLayout {
        top_count,
        footer_more: n - window.end,
        window: Some(window),
    };
    let Some(idx) = my_index else {
        return plain(LEADERBOARD_ROWS);
    };
    match mode {
        // Local player ranks outside the top 10: show the top 9, a "…", then
        // the local row.
        LeaderboardMode::Top if idx >= LEADERBOARD_ROWS => {
            split(LEADERBOARD_ROWS - 1, idx..(idx + 1).min(n))
        }
        LeaderboardMode::Top => plain(LEADERBOARD_ROWS),
        LeaderboardMode::Centered => {
            let start = idx.saturating_sub(CENTERED_NEIGHBOURS);
            let end = (idx + CENTERED_NEIGHBOURS + 1).min(n);
            // Ranks 1 to the window's end fit in the lines a split view takes
            // at most (the "…" would hide one row at most, or rows of a small
            // field): render them as one block, never shorter than the plain
            // view.
            if end <= CENTERED_SPLIT_LINES {
                plain(end.max(LEADERBOARD_ROWS))
            } else {
                split(CENTERED_TOP_ROWS, start..end)
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
    fn test_compute_gap_abandoned_is_layer_entry_delta() {
        let splits = HashMap::from([(0, 0), (1, 30000), (2, 75000), (3, 120000)]);
        // Entered layer 2 at 80000 (leader 75000) and stayed 220 s, far past
        // the leader's 45 s budget: a DNF ranks on its arrival, so no overshoot.
        let gap = compute_gap(
            300000,
            2,
            Some(80000),
            &splits,
            false,
            ParticipantStatus::Abandoned,
            120000,
            true,
        );
        assert_eq!(gap, Some(5000));
        // A layer the leader never reached has no split to compare against.
        let deeper = compute_gap(
            300000,
            4,
            Some(200000),
            &splits,
            false,
            ParticipantStatus::Abandoned,
            120000,
            true,
        );
        assert_eq!(deeper, None);
        // Everyone enters the start layer at 0: a DNF still there has no gap.
        let start_layer = compute_gap(
            60000,
            0,
            Some(0),
            &splits,
            false,
            ParticipantStatus::Abandoned,
            120000,
            true,
        );
        assert_eq!(start_layer, None);
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
        write_participant_right_text(
            &mut buf,
            ParticipantStatus::Finished,
            5,
            5,
            125_000,
            false,
            0,
        );
        assert_eq!(buf, "02:05");
    }

    #[test]
    fn test_right_text_playing_shows_layer_progress() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Playing, 0, 5, 1_000, false, 0);
        assert_eq!(buf, "1/5");
    }

    #[test]
    fn test_right_text_playing_caps_at_total() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Playing, 10, 5, 1_000, false, 0);
        assert_eq!(buf, "5/5");
    }

    #[test]
    fn test_right_text_ready_shows_status_label() {
        // Even when the race is running (non-zero layer), a ready player
        // must keep showing the "ready" label instead of a misleading "1/LAYERS".
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Ready, 0, 5, 0, false, 0);
        assert_eq!(buf, "ready");
    }

    #[test]
    fn test_right_text_registered_shows_status_label() {
        let mut buf = String::new();
        write_participant_right_text(&mut buf, ParticipantStatus::Registered, 0, 5, 0, false, 0);
        assert_eq!(buf, "registered");
    }

    #[test]
    fn test_right_text_abandoned_shows_status_label() {
        let mut buf = String::new();
        write_participant_right_text(
            &mut buf,
            ParticipantStatus::Abandoned,
            2,
            5,
            45_000,
            false,
            3,
        );
        assert_eq!(buf, "abandoned");
    }

    #[test]
    fn test_right_text_deathless_elimination_shows_dead() {
        let mut buf = String::new();
        write_participant_right_text(
            &mut buf,
            ParticipantStatus::Abandoned,
            2,
            5,
            45_000,
            true,
            1,
        );
        assert_eq!(buf, "dead");
    }

    #[test]
    fn test_right_text_deathless_abandon_without_death_stays_abandoned() {
        let mut buf = String::new();
        write_participant_right_text(
            &mut buf,
            ParticipantStatus::Abandoned,
            2,
            5,
            45_000,
            true,
            0,
        );
        assert_eq!(buf, "abandoned");
    }

    #[test]
    fn test_layout_anchor_footer_counts_only_players_below() {
        // 20 players, local is 15th (index 14): board shows top 9, "…", then
        // our anchored row, so "+ N more" must report the 5 players ranked
        // behind us, not all 10 rows that are hidden.
        let layout = compute_leaderboard_layout(20, Some(14), LeaderboardMode::Top);
        assert_eq!(layout.top_count, 9);
        assert_eq!(layout.window, Some(14..15));
        assert_eq!(layout.footer_more, 5);
    }

    #[test]
    fn test_layout_anchor_last_place_has_no_footer() {
        // Local player is dead last: nobody is behind, so no "+ N more".
        let layout = compute_leaderboard_layout(20, Some(19), LeaderboardMode::Top);
        assert_eq!(layout.window, Some(19..20));
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_layout_anchor_threshold() {
        // Smallest field that triggers an anchor: 11 players, local is last
        // (index 10). Top 9 + "…" + self = 10 rows, nobody ranked behind.
        let layout = compute_leaderboard_layout(11, Some(10), LeaderboardMode::Top);
        assert_eq!(layout.top_count, 9);
        assert_eq!(layout.window, Some(10..11));
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_layout_no_anchor_counts_hidden_tail() {
        // Local player ranks inside the top 10 (index 3): plain top-10 view, so
        // the footer counts everyone past row 10.
        let layout = compute_leaderboard_layout(20, Some(3), LeaderboardMode::Top);
        assert_eq!(layout.top_count, 10);
        assert_eq!(layout.window, None);
        assert_eq!(layout.footer_more, 10);
    }

    #[test]
    fn test_layout_spectator_no_anchor() {
        // No local player (spectator): never anchor, footer is the hidden tail,
        // whatever the mode.
        for mode in [LeaderboardMode::Top, LeaderboardMode::Centered] {
            let layout = compute_leaderboard_layout(20, None, mode);
            assert_eq!(layout.top_count, 10);
            assert_eq!(layout.window, None);
            assert_eq!(layout.footer_more, 10);
        }
    }

    #[test]
    fn test_layout_small_field_fits_without_footer() {
        // Eight players, all fit: no anchor, no footer, whatever the mode.
        for mode in [LeaderboardMode::Top, LeaderboardMode::Centered] {
            let layout = compute_leaderboard_layout(8, Some(6), mode);
            assert_eq!(layout.top_count, 8);
            assert_eq!(layout.window, None);
            assert_eq!(layout.footer_more, 0);
        }
    }

    #[test]
    fn test_layout_centered_seventh_keeps_plain_top_ten() {
        // Rank 7 (index 6): the top 10 already holds the top 3, the three
        // ahead and the three behind, so the board stays the plain top 10.
        let layout = compute_leaderboard_layout(20, Some(6), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 10);
        assert_eq!(layout.window, None);
        assert_eq!(layout.footer_more, 10);
    }

    #[test]
    fn test_layout_centered_single_hidden_row_is_shown_instead_of_separator() {
        // Rank 8 (index 7): top 3 + "…" + ranks 5-11 would hide rank 4 alone
        // behind a separator that takes its line anyway, so show ranks 1-11.
        let layout = compute_leaderboard_layout(20, Some(7), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 11);
        assert_eq!(layout.window, None);
        assert_eq!(layout.footer_more, 9);
    }

    #[test]
    fn test_layout_centered_small_field_shows_everyone() {
        // Ten runners, local player last: the whole field fits the plain
        // view, so nobody hides behind a separator.
        let layout = compute_leaderboard_layout(10, Some(9), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 10);
        assert_eq!(layout.window, None);
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_layout_centered_eleven_runners_show_everyone() {
        // Eleven runners, local player last: ranks 1-11 take no more lines
        // than a split view does at most (top 3, "…", 7 rows), so show them
        // all rather than hide ranks 4-7.
        let layout = compute_leaderboard_layout(11, Some(10), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 11);
        assert_eq!(layout.window, None);
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_leaderboard_mode_unknown_value_reads_as_centered() {
        // A newer server may write a layout this build does not know: it must
        // fall back to the default rather than reject the whole config.
        let mode: LeaderboardMode = serde_json::from_str("\"compact\"").unwrap();
        assert_eq!(mode, LeaderboardMode::Centered);
        let mode: LeaderboardMode = serde_json::from_str("\"top\"").unwrap();
        assert_eq!(mode, LeaderboardMode::Top);
    }

    #[test]
    fn test_layout_centered_window_around_player() {
        // Rank 15 (index 14): top 3, "…", ranks 12-18 (three ahead, self,
        // three behind), and the footer counts the two below the window.
        let layout = compute_leaderboard_layout(20, Some(14), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 3);
        assert_eq!(layout.window, Some(11..18));
        assert_eq!(layout.footer_more, 2);
    }

    #[test]
    fn test_layout_centered_first_split_view() {
        // Rank 9 (index 8) is the first rank that hides two rows (4 and 5),
        // so the separator appears: same line count as the 11-row block.
        let layout = compute_leaderboard_layout(20, Some(8), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 3);
        assert_eq!(layout.window, Some(5..12));
        assert_eq!(layout.footer_more, 8);
    }

    #[test]
    fn test_layout_centered_near_bottom_window_shrinks() {
        // Second to last (index 18 of 20): only one runner behind, the window
        // stays centered and shrinks rather than sliding up.
        let layout = compute_leaderboard_layout(20, Some(18), LeaderboardMode::Centered);
        assert_eq!(layout.top_count, 3);
        assert_eq!(layout.window, Some(15..20));
        assert_eq!(layout.footer_more, 0);
    }

    #[test]
    fn test_view_cycle_from_default() {
        // Default, then hidden, then the other layout, then back to default,
        // whichever layout is the default.
        for default in [LeaderboardMode::Centered, LeaderboardMode::Top] {
            let other = match default {
                LeaderboardMode::Centered => LeaderboardMode::Top,
                LeaderboardMode::Top => LeaderboardMode::Centered,
            };
            let start = LeaderboardView::Shown(default);
            let hidden = start.next(default);
            assert_eq!(hidden, LeaderboardView::Hidden);
            let alt = hidden.next(default);
            assert_eq!(alt, LeaderboardView::Shown(other));
            assert_eq!(alt.next(default), start);
        }
    }

    #[test]
    fn test_gap_reference_behind_player_is_own_gap() {
        assert_eq!(
            player_gap_reference(Some(12), Some(45_000), true),
            Some(45_000)
        );
    }

    #[test]
    fn test_gap_reference_leader_is_zero() {
        // The leader has no leader-relative gap of its own; as the reference
        // it counts for 0, leaving everyone else's gap unchanged.
        assert_eq!(player_gap_reference(Some(0), None, true), Some(0));
    }

    #[test]
    fn test_gap_reference_falls_back_without_own_gap() {
        // Disqualified, or abandoned on the start layer: no own gap, the board
        // keeps leader-relative gaps.
        assert_eq!(player_gap_reference(Some(5), None, true), None);
    }

    #[test]
    fn test_gap_reference_none_without_leader_or_player() {
        assert_eq!(player_gap_reference(Some(0), None, false), None);
        assert_eq!(player_gap_reference(None, Some(10_000), true), None);
    }

    #[test]
    fn test_gap_from_player_signs() {
        // Local player 45s behind the leader: a runner 30s behind the leader is
        // 15s ahead (negative), one 60s behind is 15s behind (positive).
        assert_eq!(
            gap_from_player(Some(30_000), false, false, 45_000),
            Some(-15_000)
        );
        assert_eq!(
            gap_from_player(Some(60_000), false, false, 45_000),
            Some(15_000)
        );
    }

    #[test]
    fn test_gap_from_player_leader_row() {
        // The leader's row carries no leader-relative gap but sits exactly the
        // local player's gap ahead.
        assert_eq!(gap_from_player(None, true, false, 45_000), Some(-45_000));
    }

    #[test]
    fn test_gap_from_player_self_and_ungapped_rows() {
        // The local row has no gap, and a row without a gap (ready,
        // disqualified) stays without one.
        assert_eq!(gap_from_player(Some(45_000), false, true, 45_000), None);
        assert_eq!(gap_from_player(None, false, false, 45_000), None);
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

    #[test]
    fn disqualified_runner_reads_dq() {
        let mut buf = String::new();
        write_participant_right_text(
            &mut buf,
            ParticipantStatus::Disqualified,
            3,
            5,
            60_000,
            false,
            0,
        );
        assert_eq!(buf, "DQ");
    }
}
