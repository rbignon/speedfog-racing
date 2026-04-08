//! Race UI - ImGui overlay for SpeedFog Racing

use std::borrow::Cow;
use std::collections::HashMap;
use std::fmt::Write;
use std::time::Duration;

use hudhook::imgui::{
    Condition, FontConfig, FontGlyphRanges, FontSource, Image, StyleColor, WindowFlags,
};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::{error, info};

use super::death_icon::DeathIcon;
use super::tracker::{FlagReadResult, RaceTracker, RenderBuffers};
use super::websocket::ConnectionStatus;

impl ImguiRenderLoop for RaceTracker {
    fn initialize<'a>(
        &'a mut self,
        ctx: &mut hudhook::imgui::Context,
        render_context: &'a mut dyn RenderContext,
    ) {
        if let Some(ref font_data) = self.font_data {
            let font_size = self.config.overlay.font_size;

            // Glyph ranges: Basic Latin + Punctuation + Box/Geometric + Arrows + Dagger
            let glyph_ranges = FontGlyphRanges::from_slice(&[
                0x0020, 0x00FF, // Basic Latin + Latin Supplement
                0x2000, 0x206F, // General Punctuation (…, –)
                0x2500, 0x25FF, // Box Drawing + Block Elements + Geometric Shapes (●)
                0x2190, 0x21FF, // Arrows (→)
                0,
            ]);

            ctx.fonts().add_font(&[FontSource::TtfData {
                data: font_data,
                size_pixels: font_size,
                config: Some(FontConfig {
                    glyph_ranges,
                    ..FontConfig::default()
                }),
            }]);

            info!(size = font_size, "Custom font registered with imgui");
        } else {
            info!("Using default imgui font");
        }

        // Load death icon texture.
        // Wrapped in catch_unwind because render_context.load_texture() can panic
        // when the DX12 command queue isn't fully initialized yet.
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            DeathIcon::load(render_context)
        })) {
            Ok(Ok(icon)) => {
                info!("Loaded death icon texture");
                self.death_icon = Some(icon);
            }
            Ok(Err(e)) => {
                error!(error = %e, "Failed to load death icon");
            }
            Err(_) => {
                error!("Death icon texture load panicked (DX12 not ready?)");
            }
        }
    }

    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        // Per-frame update
        self.update();

        // Always build a window (hudhook crashes otherwise)
        if !self.show_ui {
            ui.window("##hidden")
                .position([-100.0, -100.0], Condition::Always)
                .size([1.0, 1.0], Condition::Always)
                .no_decoration()
                .build(|| {});
            return;
        }

        // Take pre-allocated buffers out of self so sub-methods can borrow
        // self immutably while mutating the buffers.
        let mut bufs = std::mem::take(&mut self.render_bufs);

        let c = &self.cached_colors;

        // Push style colors (auto-popped when tokens drop)
        let _bg_token = ui.push_style_color(StyleColor::WindowBg, c.bg);
        let _text_token = ui.push_style_color(StyleColor::Text, c.text);
        let _text_disabled_token = ui.push_style_color(StyleColor::TextDisabled, c.text_disabled);
        let _border_token = ui.push_style_color(StyleColor::Border, c.border);

        let [dw, _dh] = ui.io().display_size;
        let scale = self.config.overlay.font_size / 16.0;
        let max_width = 320.0 * scale;

        let flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        ui.window("SpeedFog Race")
            .position(
                [
                    dw - max_width - self.config.overlay.position_offset_x,
                    self.config.overlay.position_offset_y,
                ],
                Condition::FirstUseEver,
            )
            .flags(flags)
            .build(|| {
                self.render_seed_mismatch_warning(ui);
                self.render_player_status(ui, max_width, &mut bufs);
                self.render_exits(ui, max_width);
                if !self.config.server.training && self.show_leaderboard {
                    ui.separator();
                    self.render_leaderboard(ui, max_width, &mut bufs);
                }
                self.render_status_message(ui);
                if self.show_debug {
                    ui.separator();
                    self.render_debug(ui);
                }
            });

        // Put buffers back (preserves capacity for next frame)
        self.render_bufs = bufs;
    }
}

impl RaceTracker {
    /// Write the IGT display string into a buffer.
    fn write_igt(&self, buf: &mut String) {
        if self.am_i_finished() {
            if let Some(me) = self.my_participant().filter(|p| p.igt_ms > 0) {
                write_time_u32(buf, me.igt_ms as u32);
            } else {
                buf.push_str("--:--:--");
            }
        } else if let Some(frozen) = self.frozen_igt_ms {
            write_time_u32(buf, frozen);
        } else if !self.is_race_running() {
            buf.push_str("--:--:--");
        } else if let Some(igt_ms) = self.read_igt() {
            write_time_u32(buf, igt_ms);
        } else {
            buf.push_str("--:--:--");
        }
    }

    /// Red warning when the config's seed_id doesn't match the server's seed_id.
    /// This means the player has an outdated seed pack after a re-roll.
    fn render_seed_mismatch_warning(&self, ui: &hudhook::imgui::Ui) {
        if self.seed_mismatch {
            let red = [1.0, 0.2, 0.2, 1.0];
            ui.text_colored(red, "SEED OUTDATED");
            ui.text_colored(red, "Re-download your seed pack");
        }
    }

    /// 3-line player status:
    /// Line 1: `● RaceName               HH:MM:SS` (name dimmed, right side in blue)
    ///         Right side shows: WAITING (setup), countdown/GO! (start), IGT (running)
    /// Line 2: `  ZoneName                    X/Y` (X yellow→green on finish, /Y white)
    /// Line 3: `  tier X, normally Y   [☠]N`          (tier yellow, deaths white)
    fn render_player_status(
        &self,
        ui: &hudhook::imgui::Ui,
        max_width: f32,
        bufs: &mut RenderBuffers,
    ) {
        let buf_right = &mut bufs.buf_right;
        let buf_left = &mut bufs.buf_left;
        buf_right.clear();
        buf_left.clear();

        let blue = [0.4, 0.6, 1.0, 1.0];
        let yellow = [1.0, 1.0, 0.0, 1.0];
        let green = [0.0, 1.0, 0.0, 1.0];

        // --- Line 1: connection dot + race name (left), local IGT in blue (right) ---
        let dot_color = if self.permanent_error.is_some() {
            [1.0, 0.0, 0.0, 1.0] // red
        } else {
            match self.ws_status() {
                ConnectionStatus::Connected => green,
                ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => {
                    [1.0, 0.65, 0.0, 1.0]
                }
                _ => [1.0, 0.0, 0.0, 1.0],
            }
        };

        // Right side of line 1: state banner during setup/countdown/go, IGT otherwise.
        let orange = [1.0, 0.75, 0.0, 1.0];
        let status_str = self.race_info().map(|r| r.status.as_str()).unwrap_or("");

        let right_color = match status_str {
            "setup" => {
                buf_right.push_str("WAITING");
                orange
            }
            "running" => {
                // Countdown: "3", "2", "1" in yellow; then "GO!" in green for 3s
                let countdown_secs = self.race_state.countdown_end.and_then(|end| {
                    end.checked_duration_since(std::time::Instant::now())
                        .map(|remaining| remaining.as_secs() + 1)
                });
                if let Some(secs) = countdown_secs {
                    write!(buf_right, "{}", secs).ok();
                    yellow
                } else if let Some(go_start) = self
                    .race_state
                    .countdown_end
                    .or(self.race_state.race_started_at)
                {
                    if go_start.elapsed() < Duration::from_secs(3) {
                        buf_right.push_str("GO!");
                        green
                    } else {
                        self.write_igt(buf_right);
                        blue
                    }
                } else {
                    // Reconnect: no race_start received, skip GO! phase
                    self.write_igt(buf_right);
                    blue
                }
            }
            "finished" => {
                self.write_igt(buf_right);
                green
            }
            _ => {
                self.write_igt(buf_right);
                blue
            }
        };
        let igt_width = ui.calc_text_size(&buf_right)[0];

        let dot_str = "\u{25CF} "; // "● "
        let dot_width = ui.calc_text_size(dot_str)[0];
        let gap = ui.calc_text_size(" ")[0];
        let name_max = max_width - igt_width - gap - dot_width;

        ui.text_colored(dot_color, dot_str);
        ui.same_line_with_spacing(0.0, 0.0);

        if let Some(race) = self.race_info() {
            buf_left.push_str(&race.name);
        } else {
            buf_left.push_str("Connecting...");
        }
        let truncated = truncate_to_width(ui, &buf_left, name_max);
        ui.text_colored(self.cached_colors.text_disabled, &truncated);

        ui.same_line_with_pos(max_width - igt_width);
        ui.text_colored(right_color, &buf_right);

        // --- Line 2: zone name (left, white), progress X/Y (right, X=yellow/green Y=white) ---
        buf_right.clear();
        buf_left.clear();

        let me = self.my_participant();
        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let zone = self.current_zone_info();
        let frozen_layer = self.pre_reveal_layer();

        let is_setup = self
            .race_info()
            .is_some_and(|r| r.status.as_str() == "setup");

        // In setup phase, show participant status instead of layer progress
        let right_color = if is_setup {
            let status = me.map(|p| p.status.as_str()).unwrap_or("registered");
            let orange = [1.0, 0.65, 0.0, 1.0];
            buf_right.push_str(status);
            match status {
                "ready" => orange,
                _ => self.cached_colors.text_disabled,
            }
        } else {
            let layer = frozen_layer
                .or_else(|| me.map(|p| p.current_layer))
                .unwrap_or(0);
            let display_layer = (layer + 1).min(total_layers);
            write!(buf_right, "{}/{}", display_layer, total_layers).ok();
            if self.am_i_finished() {
                green
            } else {
                yellow
            }
        };
        let right_width = ui.calc_text_size(&buf_right)[0];

        if let Some(z) = zone {
            write!(buf_left, "  {}", z.display_name).ok();
        }
        let zone_max = max_width - right_width - gap;
        let zone_truncated = truncate_to_width(ui, &buf_left, zone_max);
        ui.text(&zone_truncated);

        ui.same_line_with_pos(max_width - right_width);
        ui.text_colored(right_color, &buf_right);

        // --- Line 3: tier info (left, yellow), death icon + count (right, white) ---
        buf_right.clear();
        buf_left.clear();

        let deaths = self.read_deaths().unwrap_or(0);
        write!(buf_right, "{}", deaths).ok();
        let font_height = ui.text_line_height();
        let icon_size = font_height;
        let icon_gap = 2.0;
        let right_total = if self.death_icon.is_some() {
            icon_size + icon_gap + ui.calc_text_size(&buf_right)[0]
        } else {
            ui.calc_text_size(&buf_right)[0]
        };

        let current_layer = frozen_layer
            .or_else(|| me.map(|p| p.current_layer))
            .unwrap_or(0);
        if let Some(z) = zone {
            if let Some(t) = z.tier {
                if let Some(ot) = z.original_tier.filter(|&ot| ot != t) {
                    write!(buf_left, "  tier {}, normally {}", t, ot).ok();
                } else {
                    write!(buf_left, "  tier {}", t).ok();
                }
                // Show current layer when backtracking (zone layer < max layer reached)
                if let Some(zl) = z.layer {
                    if zl < current_layer {
                        write!(buf_left, ", layer {}/{}", zl + 1, total_layers).ok();
                    }
                }
            }
        } else if frozen_layer.is_none() {
            // Only fall back to current_layer_tier when NOT waiting for reveal,
            // otherwise this would show the new zone's tier before its name.
            if let Some(tier) = me.and_then(|p| p.current_layer_tier) {
                write!(buf_left, "  tier {}", tier).ok();
            }
        }
        let has_tier = zone.is_some_and(|z| z.tier.is_some())
            || me.is_some_and(|p| p.current_layer_tier.is_some());
        let tier_color = if has_tier {
            yellow
        } else {
            self.cached_colors.text
        };

        let tier_max = max_width - right_total - gap;
        let tier_truncated = truncate_to_width(ui, &buf_left, tier_max);
        ui.text_colored(tier_color, &tier_truncated);

        ui.same_line_with_pos(max_width - right_total);
        if let Some(ref icon) = self.death_icon {
            Image::new(icon.texture_id(), [icon_size, icon_size]).build(ui);
            ui.same_line_with_spacing(0.0, icon_gap);
        }
        ui.text_colored(self.cached_colors.text, &buf_right);
    }

    /// Render exit list from zone_update:
    /// ```text
    /// → Ruin-Strewn Precipice          (green, discovered)
    ///   Stranded Graveyard first door   (gray, word-wrapped)
    /// → ???                             (white, undiscovered)
    ///   Soldier of Godrick front        (gray, word-wrapped)
    /// ```
    fn render_exits(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let zone = match self.current_zone_info() {
            Some(z) if !z.exits.is_empty() => z,
            _ => return,
        };

        let green = [0.0, 1.0, 0.0, 1.0];
        let white = self.cached_colors.text;
        let indent = "  ";

        for exit in &zone.exits {
            // Line 1: destination (green if discovered, white "???" if not)
            if exit.discovered {
                let dest = format!("\u{2192} {}", exit.to_name);
                let truncated = truncate_to_width(ui, &dest, max_width);
                ui.text_colored(green, &truncated);
            } else {
                ui.text_colored(white, "\u{2192} ???");
            }

            // Lines 2+: directions to reach the fog gate (gray, word-wrapped)
            for line in wrap_text(ui, indent, &exit.text, max_width) {
                ui.text_disabled(&line);
            }
        }
    }

    /// Render a single leaderboard row with optional gap column.
    /// `{rank}. {name}   [+/-gap]   {progress_or_time}`
    ///
    /// Accepts pre-computed `right_text` and `gap_text` (built by the caller into
    /// reusable buffers), plus a `left_buf` for internal name formatting.
    fn render_participant_row(
        &self,
        ui: &hudhook::imgui::Ui,
        p: &crate::core::protocol::ParticipantInfo,
        rank: usize,
        max_width: f32,
        spacing: f32,
        is_self: bool,
        gap_col_width: f32,
        right_col_width: f32,
        right_text: &str,
        gap_text: Option<&str>,
        computed_gap_ms: Option<i32>,
        left_buf: &mut String,
    ) {
        let name = p
            .twitch_display_name
            .as_deref()
            .unwrap_or(&p.twitch_username);

        let base_color = match p.status.as_str() {
            "finished" => [0.0, 1.0, 0.0, 1.0],
            "playing" => self.cached_colors.text,
            "ready" => [1.0, 0.65, 0.0, 1.0],
            _ => self.cached_colors.text_disabled,
        };
        let color = if is_self {
            brighten(base_color, 0.35)
        } else {
            base_color
        };

        // Layout: [name]  [gap right-aligned in gap_col]  [right right-aligned]
        let right_x = max_width - right_col_width;
        let gap_x = if gap_col_width > 0.0 {
            right_x - spacing - gap_col_width
        } else {
            right_x
        };

        // Left (name): truncate to fit before gap column
        left_buf.clear();
        write!(left_buf, "{:2}. {}", rank, name).ok();
        let left_max = gap_x - spacing;
        let truncated = truncate_to_width(ui, left_buf, left_max);
        ui.text_colored(color, &truncated);

        // Gap (right-aligned within gap column, color-coded)
        if let Some(gt) = gap_text {
            let gap_color = match computed_gap_ms {
                Some(ms) if ms < 0 => [0.3, 0.9, 0.3, 1.0], // green: ahead of pace
                Some(ms) if ms > 0 => [0.9, 0.35, 0.35, 1.0], // soft red: behind
                _ => color,
            };
            let gt_width = ui.calc_text_size(gt)[0];
            ui.same_line_with_pos(gap_x + gap_col_width - gt_width);
            ui.text_colored(gap_color, gt);
        }

        // Right (right-aligned)
        let rt_width = ui.calc_text_size(right_text)[0];
        ui.same_line_with_pos(max_width - rt_width);
        ui.text_colored(color, right_text);
    }

    /// Leaderboard with color-coded status, gap timing, and right-aligned values.
    /// Gaps are computed client-side using leader_splits. The local player uses
    /// real-time game memory IGT; other players use the server's latest snapshot.
    /// Always shows the local player: if ranked beyond top 10, anchors them
    /// at the bottom with a `···` separator and their real rank.
    fn render_leaderboard(
        &self,
        ui: &hudhook::imgui::Ui,
        max_width: f32,
        bufs: &mut RenderBuffers,
    ) {
        let participants = self.participants();
        if participants.is_empty() {
            ui.text_disabled("No participants");
            return;
        }

        let buf_right = &mut bufs.buf_right;
        let buf_gap = &mut bufs.buf_gap;
        let buf_left = &mut bufs.buf_left;
        let buf_footer = &mut bufs.buf_footer;

        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let is_setup = self
            .race_info()
            .is_some_and(|r| r.status.as_str() == "setup");
        let spacing = ui.calc_text_size(" ")[0];

        // Get leader_splits and leader IGT for gap computation
        // Empty HashMap doesn't allocate until first insert, so this is free.
        let empty_splits = HashMap::new();
        let leader_splits = self
            .race_state
            .leader_splits
            .as_ref()
            .unwrap_or(&empty_splits);

        // Local IGT for self (real-time updates from game memory)
        let local_igt = self.read_igt().map(|v| v as i32);
        let my_id = self.my_participant_id();

        let leader_igt_ms = participants
            .first()
            .filter(|p| p.status == "playing" || p.status == "finished")
            .map(|p| {
                // Use real-time game IGT if we are the leader
                if my_id.is_some_and(|id| id == &p.id) {
                    local_igt.unwrap_or(p.igt_ms)
                } else {
                    p.igt_ms
                }
            })
            .unwrap_or(0);
        let has_leader = !leader_splits.is_empty()
            || participants.first().is_some_and(|p| p.status == "finished");
        let leader_finished = participants.first().is_some_and(|p| p.status == "finished");

        // Pre-compute gaps for all participants (reuse pre-allocated Vec)
        let race_finished = self
            .race_info()
            .is_some_and(|r| r.status.as_str() == "finished");

        let gaps = &mut bufs.gaps;
        gaps.clear();
        for (i, p) in participants.iter().enumerate() {
            let gap = if !has_leader {
                None
            } else if p.status == "finished" || race_finished {
                // Finished players or race ended: use server-computed gap (frozen)
                p.gap_ms
            } else {
                // Use real-time game IGT for self, server snapshot for others
                let igt = if my_id.is_some_and(|id| id == &p.id) {
                    local_igt.unwrap_or(p.igt_ms)
                } else {
                    p.igt_ms
                };
                crate::core::compute_gap(
                    igt,
                    p.current_layer,
                    p.layer_entry_igt,
                    leader_splits,
                    i == 0,
                    &p.status,
                    leader_igt_ms,
                    leader_finished,
                )
            };
            gaps.push(gap);
        }

        // Pre-compute column widths using reusable buffers
        let mut max_gap_width: f32 = 0.0;
        let mut max_right_width: f32 = 0.0;
        for (i, p) in participants.iter().enumerate() {
            buf_right.clear();
            write_right_text(buf_right, p, total_layers, is_setup);
            let rw = ui.calc_text_size(&buf_right)[0];
            if rw > max_right_width {
                max_right_width = rw;
            }
            if let Some(gap_ms) = gaps[i] {
                buf_gap.clear();
                crate::core::format_gap_into(buf_gap, gap_ms);
                let gw = ui.calc_text_size(&buf_gap)[0];
                if gw > max_gap_width {
                    max_gap_width = gw;
                }
            }
        }

        // Find local player's index in the (pre-sorted) participants list
        let my_index = my_id.and_then(|my_id| participants.iter().position(|p| &p.id == my_id));

        // Determine how many top rows to show and whether to anchor self
        let need_anchor = participants.len() > 10 && my_index.map_or(false, |idx| idx >= 10);
        let top_count = if need_anchor {
            9
        } else {
            10.min(participants.len())
        };

        // Helper: prepare buffers and render one participant row
        let mut emit_row =
            |idx: usize, rank: usize, is_self: bool, p: &crate::core::protocol::ParticipantInfo| {
                buf_right.clear();
                write_right_text(buf_right, p, total_layers, is_setup);

                let gap_str = if let Some(gap_ms) = gaps[idx] {
                    buf_gap.clear();
                    crate::core::format_gap_into(buf_gap, gap_ms);
                    Some(buf_gap.as_str())
                } else {
                    None
                };

                self.render_participant_row(
                    ui,
                    p,
                    rank,
                    max_width,
                    spacing,
                    is_self,
                    max_gap_width,
                    max_right_width,
                    buf_right,
                    gap_str,
                    gaps[idx],
                    buf_left,
                );
            };

        // Render top rows
        for (i, p) in participants.iter().take(top_count).enumerate() {
            emit_row(i, i + 1, my_index == Some(i), p);
        }

        // Anchor: separator + self row
        if need_anchor {
            if let Some(idx) = my_index {
                ui.text_disabled("  \u{00B7}\u{00B7}\u{00B7}");
                emit_row(idx, idx + 1, true, &participants[idx]);
            }
        }

        // "+ N more" footer
        let displayed = if need_anchor {
            top_count + if my_index.is_some() { 1 } else { 0 }
        } else {
            top_count
        };
        if participants.len() > displayed {
            buf_footer.clear();
            write!(buf_footer, "  + {} more", participants.len() - displayed).ok();
            ui.text_disabled(buf_footer);
        }
    }

    /// Status message: persistent red for permanent errors, temporary yellow otherwise.
    fn render_status_message(&self, ui: &hudhook::imgui::Ui) {
        // Permanent errors are always visible (red)
        if let Some(ref err) = self.permanent_error {
            ui.separator();
            ui.text_colored([1.0, 0.3, 0.3, 1.0], err);
            return;
        }
        // Temporary status messages (yellow, auto-dismiss)
        if let Some(status) = self.get_status() {
            ui.separator();
            ui.text_colored([1.0, 1.0, 0.0, 1.0], status);
        }
    }

    fn render_debug(&self, ui: &hudhook::imgui::Ui) {
        ui.text_colored([1.0, 0.85, 0.3, 1.0], "Debug");

        let debug = self.debug_info();

        // Zones: show each participant's current_zone
        ui.text_disabled("Zones:");
        let participants = self.participants();
        if participants.is_empty() {
            ui.text("  \u{2013}");
        } else {
            for p in participants {
                let name = p
                    .twitch_display_name
                    .as_deref()
                    .unwrap_or(&p.twitch_username);
                let zone = p.current_zone.as_deref().unwrap_or("\u{2013}");
                ui.text(format!("  {}: {}", name, zone));
            }
        }

        // Flag reader diagnostics
        ui.text_disabled("Flag reader:");
        ui.same_line();
        let status_color = if debug.flag_reader_ok {
            [0.0, 1.0, 0.0, 1.0] // green
        } else {
            [1.0, 0.3, 0.3, 1.0] // red
        };
        ui.text_colored(status_color, &debug.flag_reader_status);

        // Vanilla flag sanity check (category 0 should always exist)
        let (sanity_color, sanity_label) = match &debug.vanilla_sanity {
            FlagReadResult::Set => ([0.0, 1.0, 0.0, 1.0], "true"),
            FlagReadResult::NotSet => (self.cached_colors.text, "false"),
            FlagReadResult::Unreadable => ([1.0, 0.3, 0.3, 1.0], "None"),
        };
        ui.text("  vanilla 6:");
        ui.same_line();
        ui.text_colored(sanity_color, sanity_label);

        if !debug.sample_reads.is_empty() {
            for (flag_id, result) in &debug.sample_reads {
                let (color, label) = match result {
                    FlagReadResult::Set => ([0.0, 1.0, 0.0, 1.0], "true"),
                    FlagReadResult::NotSet => (self.cached_colors.text, "false"),
                    FlagReadResult::Unreadable => ([1.0, 0.3, 0.3, 1.0], "None"),
                };
                ui.text(format!("  {}:", flag_id));
                ui.same_line();
                ui.text_colored(color, label);
            }
        }

        // Last sent message
        ui.text_disabled("Sent:");
        ui.same_line();
        ui.text(debug.last_sent.as_deref().unwrap_or("\u{2013}"));

        // Last received message
        ui.text_disabled("Recv:");
        ui.same_line();
        ui.text(debug.last_received.as_deref().unwrap_or("\u{2013}"));
    }
}

/// Brighten a color by mixing it toward white.
fn brighten(color: [f32; 4], factor: f32) -> [f32; 4] {
    [
        color[0] + (1.0 - color[0]) * factor,
        color[1] + (1.0 - color[1]) * factor,
        color[2] + (1.0 - color[2]) * factor,
        color[3],
    ]
}

/// Write right-column text for a participant row into a buffer.
/// Produces: finish time, layer progress, or status label.
fn write_right_text(
    buf: &mut String,
    p: &crate::core::protocol::ParticipantInfo,
    total_layers: i32,
    is_setup: bool,
) {
    match p.status.as_str() {
        "finished" => write_time(buf, p.igt_ms),
        "ready" if is_setup => buf.push_str("ready"),
        "registered" if is_setup => buf.push_str("registered"),
        _ if is_setup => buf.push_str(&p.status),
        _ => {
            let display = (p.current_layer + 1).min(total_layers);
            write!(buf, "{}/{}", display, total_layers).ok();
        }
    }
}

/// Write a time value (signed ms) as M:SS or H:MM:SS into a buffer.
fn write_time(buf: &mut String, ms: i32) {
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

/// Write a time value (unsigned ms) as HH:MM:SS into a buffer.
fn write_time_u32(buf: &mut String, ms: u32) {
    let secs = ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    write!(buf, "{:02}:{:02}:{:02}", hours, mins % 60, secs % 60).ok();
}

/// Word-wrap `text` into lines that fit within `max_width`, prepending `indent` to each line.
fn wrap_text(ui: &hudhook::imgui::Ui, indent: &str, text: &str, max_width: f32) -> Vec<String> {
    let full = format!("{}{}", indent, text);
    if ui.calc_text_size(&full)[0] <= max_width {
        return vec![full];
    }

    let mut lines = Vec::new();
    let mut current_line = indent.to_string();
    for word in text.split_whitespace() {
        let candidate = if current_line.len() == indent.len() {
            format!("{}{}", current_line, word)
        } else {
            format!("{} {}", current_line, word)
        };

        if ui.calc_text_size(&candidate)[0] <= max_width {
            current_line = candidate;
        } else if current_line.len() == indent.len() {
            // Single word exceeds max_width, truncate it
            let truncated = truncate_to_width(ui, &candidate, max_width);
            lines.push(truncated.into_owned());
        } else {
            lines.push(current_line);
            current_line = format!("{}{}", indent, word);
        }
    }
    if current_line.len() > indent.len() {
        lines.push(current_line);
    }

    lines
}

/// Truncate text to fit within `max_width` pixels, adding "\u{2026}" if needed.
///
/// Returns `Cow::Borrowed` when the text fits (zero allocations in the common case).
/// When truncation is needed, does a linear forward scan and one allocation for the result.
fn truncate_to_width<'a>(ui: &hudhook::imgui::Ui, text: &'a str, max_width: f32) -> Cow<'a, str> {
    if ui.calc_text_size(text)[0] <= max_width {
        return Cow::Borrowed(text);
    }

    let ellipsis = "\u{2026}"; // …
    let ellipsis_width = ui.calc_text_size(ellipsis)[0];
    let target_width = max_width - ellipsis_width;
    if target_width <= 0.0 {
        return Cow::Borrowed(ellipsis);
    }

    // Linear forward scan: find the longest byte prefix that fits
    let mut last_fit = 0;
    for (byte_pos, _) in text.char_indices().skip(1) {
        if ui.calc_text_size(&text[..byte_pos])[0] > target_width {
            break;
        }
        last_fit = byte_pos;
    }

    Cow::Owned(format!("{}{}", &text[..last_fit], ellipsis))
}
