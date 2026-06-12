//! Race UI - ImGui overlay for SpeedFog Racing

use std::borrow::Cow;
use std::fmt::Write;
use std::time::Duration;

use hudhook::imgui::{
    Condition, FontConfig, FontGlyphRanges, FontSource, Image, StyleColor, WindowFlags,
};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::{error, info};

use crate::core::write_participant_right_text;
use crate::profile_span;

use super::config::OverlayAnchor;
use super::death_icon::DeathIcon;
use super::tracker::{
    FlagReadResult, LeaderboardRowCache, RaceTracker, RenderBuffers,
    LEADERBOARD_REFRESH_INTERVAL_MS,
};
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
            Err(payload) => {
                error!(
                    panic = crate::panic_message(payload.as_ref()),
                    "Death icon texture load panicked (DX12 not ready?)"
                );
            }
        }
    }

    fn render(&mut self, ui: &mut hudhook::imgui::Ui) {
        if self.render_panicked {
            build_hidden_window(ui);
            crate::core::profile::frame_mark();
            return;
        }
        if let Err(payload) =
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.render_frame(ui)))
        {
            self.render_panicked = true;
            error!(
                panic = crate::panic_message(payload.as_ref()),
                "Render panicked; overlay disabled until the game restarts"
            );
            build_hidden_window(ui);
            crate::core::profile::frame_mark();
        }
    }
}

impl RaceTracker {
    fn render_frame(&mut self, ui: &hudhook::imgui::Ui) {
        profile_span!("frame");

        // Per-frame update
        self.update(ui);

        // Always build a window (hudhook crashes otherwise)
        if !self.show_ui {
            build_hidden_window(ui);
            crate::core::profile::frame_mark();
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

        let [dw, dh] = ui.io().display_size;
        let scale = self.config.overlay.font_size / 16.0;
        let max_width = 320.0 * scale;

        // Pin the window's anchored corner via pivot so the actual
        // auto-resized edge is pinned, not an estimated width.
        let ox = self.config.overlay.position_offset_x;
        let oy = self.config.overlay.position_offset_y;
        let (pos, pivot) = match self.config.overlay.anchor {
            OverlayAnchor::TopLeft => ([ox, oy], [0.0, 0.0]),
            OverlayAnchor::TopRight => ([dw - ox, oy], [1.0, 0.0]),
            OverlayAnchor::BottomLeft => ([ox, dh - oy], [0.0, 1.0]),
            OverlayAnchor::BottomRight => ([dw - ox, dh - oy], [1.0, 1.0]),
        };

        let flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        {
            profile_span!("imgui_window");
            ui.window("SpeedFog Race")
                .position(pos, Condition::Always)
                .position_pivot(pivot)
                .flags(flags)
                .build(|| {
                    self.render_seed_mismatch_warning(ui);
                    self.render_player_status(ui, max_width, &mut bufs);
                    self.render_race_ends_warning(ui, max_width);
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
        }

        // Put buffers back (preserves capacity for next frame)
        self.render_bufs = bufs;

        crate::core::profile::frame_mark();
    }

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

    /// Danger banner shown when the config's seed_id doesn't match the server's
    /// seed_id. This means the player has an outdated seed pack after a re-roll.
    fn render_seed_mismatch_warning(&self, ui: &hudhook::imgui::Ui) {
        if self.seed_mismatch {
            let danger = self.cached_colors.danger;
            ui.text_colored(danger, "SEED OUTDATED");
            ui.text_colored(danger, "Re-download your seed pack");
        }
    }

    /// Amber countdown shown right-aligned when a running race has less than
    /// 30 minutes remaining. Only shown while the race is RUNNING and
    /// race_ends_at is in the future.
    fn render_race_ends_warning(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        if let Some(race_info) = self.race_info() {
            if race_info.status == "running" {
                if let Some(ends_at_dt) = race_info.race_ends_at_dt {
                    let remaining_seconds = ends_at_dt
                        .signed_duration_since(chrono::Utc::now())
                        .num_seconds();
                    if remaining_seconds > 0 && remaining_seconds < 1800 {
                        let mins = remaining_seconds / 60;
                        let secs = remaining_seconds % 60;
                        let text = format!("{}:{:02} left", mins, secs);
                        let text_width = ui.calc_text_size(&text)[0];
                        let y = ui.cursor_pos()[1];
                        ui.set_cursor_pos([max_width - text_width, y]);
                        ui.text_colored(self.cached_colors.gold, text);
                    }
                }
            }
        }
    }

    /// 3-line player status:
    /// Line 1: `● RaceName               HH:MM:SS` (name dimmed, right side highlighted)
    ///         Right side shows: WAITING (setup, gold), countdown/GO! (start, gold/emerald),
    ///         IGT (running, purple), or finished IGT (emerald/danger-dark on abandon).
    /// Line 2: `  ZoneName                    X/Y` (X/Y gold while playing, emerald on finish)
    /// Line 3: `  tier X, normally Y   [☠]N`     (tier gold; deaths white)
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

        let c = &self.cached_colors;
        let purple = c.purple;
        let gold = c.gold;
        let success = c.success;

        // --- Line 1: connection dot + race name (left), local IGT highlighted (right) ---
        let dot_color = if self.permanent_error.is_some() {
            c.danger
        } else {
            match self.ws_status() {
                ConnectionStatus::Connected => success,
                ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => gold,
                _ => c.danger,
            }
        };

        // Right side of line 1: state banner during setup/countdown/go, IGT otherwise.
        let status_str = self.race_info().map(|r| r.status.as_str()).unwrap_or("");
        let i_abandoned = self
            .my_participant()
            .is_some_and(|p| p.status == "abandoned");

        let right_color = match status_str {
            "setup" => {
                buf_right.push_str("WAITING");
                gold
            }
            "running" => {
                let countdown_secs = self.race_state.countdown_end.and_then(|end| {
                    end.checked_duration_since(std::time::Instant::now())
                        .map(|remaining| remaining.as_secs() + 1)
                });
                if let Some(secs) = countdown_secs {
                    write!(buf_right, "{}", secs).ok();
                    gold
                } else if let Some(go_start) = self
                    .race_state
                    .countdown_end
                    .or(self.race_state.race_started_at)
                {
                    if go_start.elapsed() < Duration::from_secs(3) {
                        buf_right.push_str("GO!");
                        success
                    } else {
                        self.write_igt(buf_right);
                        purple
                    }
                } else {
                    self.write_igt(buf_right);
                    purple
                }
            }
            "finished" => {
                self.write_igt(buf_right);
                if i_abandoned {
                    c.danger_dark
                } else {
                    success
                }
            }
            _ => {
                self.write_igt(buf_right);
                purple
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

        // --- Line 2: zone name (left), progress X/Y (right; X status-colored, /Y default) ---
        buf_right.clear();
        buf_left.clear();

        let me = self.my_participant();
        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let zone = self.current_zone_info();
        let frozen_layer = self.pre_reveal_layer();

        // Show layer progress only while actively playing or finished; otherwise
        // show the participant status so pre-launch states (registered/ready)
        // stay visible once the race leaves setup.
        let my_status = me.map(|p| p.status.as_str()).unwrap_or("registered");

        let right_color = if my_status == "playing" || my_status == "finished" {
            let layer = frozen_layer
                .or_else(|| me.map(|p| p.current_layer))
                .unwrap_or(0);
            let display_layer = (layer + 1).min(total_layers);
            write!(buf_right, "{}/{}", display_layer, total_layers).ok();
            if my_status == "finished" {
                success
            } else {
                gold
            }
        } else {
            buf_right.push_str(my_status);
            if my_status == "ready" {
                gold
            } else {
                c.text_disabled
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

        // --- Line 3: tier info (left), death icon + count (right) ---
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
                        write!(buf_left, ", depth {}/{}", zl + 1, total_layers).ok();
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
        let tier_color = if has_tier { gold } else { c.text };

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
    /// → Ruin-Strewn Precipice          (discovered, highlighted)
    ///   Stranded Graveyard first door   (description, dimmed)
    /// → ???                             (undiscovered)
    ///   Soldier of Godrick front        (description, dimmed)
    /// ```
    fn render_exits(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let zone = match self.current_zone_info() {
            Some(z) if !z.exits.is_empty() => z,
            _ => return,
        };

        let c = &self.cached_colors;
        let success = c.success;
        let white = c.text;
        let indent = "  ";

        for exit in &zone.exits {
            // Line 1: destination (highlighted if discovered, "???" placeholder if not)
            if exit.discovered {
                let dest = format!("\u{2192} {}", exit.to_name);
                let truncated = truncate_to_width(ui, &dest, max_width);
                ui.text_colored(success, &truncated);
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
        name_color: Option<&crate::dll::tracker::ResolvedNameColor>,
    ) {
        let name = p
            .twitch_display_name
            .as_deref()
            .unwrap_or(&p.twitch_username);

        let c = &self.cached_colors;
        let base_color = match p.status.as_str() {
            "finished" => c.success,
            "playing" => c.text,
            "ready" => c.gold,
            _ => c.text_disabled,
        };
        // Local player keeps the charter purple unless abandoned; abandoned
        // stays greyed so the row reads as inactive even when it's mine.
        let color = if is_self && p.status != "abandoned" {
            c.purple
        } else {
            base_color
        };

        // Local player gets a translucent purple fill across the row. Drawn
        // before the text so subsequent ui.text_colored calls render on top.
        if is_self && p.status != "abandoned" {
            let dl = ui.get_window_draw_list();
            let [sx, sy] = ui.cursor_screen_pos();
            let row_h = ui.text_line_height_with_spacing();
            // Extend the fill 4px to the left so it hugs the window's content
            // padding instead of starting flush with the rank number.
            const PAD: f32 = 4.0;
            dl.add_rect([sx - PAD, sy], [sx + max_width, sy + row_h], c.purple_bg)
                .filled(true)
                .build();
        }

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

        // Split "12. NAME" into the rank prefix (status-colored) and the name
        // (template-colored or status-colored fallback).
        // Prefix is "{rank:2}. ", 4 bytes for ranks 1-99 but 5+ for 100+, so we
        // locate ". " dynamically rather than hardcoding the length.
        let truncated_str: &str = truncated.as_ref();
        let prefix_len = truncated_str.find(". ").map(|i| i + 2).unwrap_or(0);
        if prefix_len == 0 || truncated_str.len() <= prefix_len {
            // Pathological narrow column or no separator found: render the whole thing in status color.
            ui.text_colored(color, truncated_str);
        } else {
            let (prefix, name_part) = truncated_str.split_at(prefix_len);
            ui.text_colored(color, prefix);
            ui.same_line_with_spacing(0.0, 0.0);
            match name_color {
                Some(crate::dll::tracker::ResolvedNameColor::Solid(c)) => {
                    ui.text_colored(*c, name_part);
                }
                Some(crate::dll::tracker::ResolvedNameColor::Gradient(c0, c1)) => {
                    let char_count = name_part.chars().count();
                    if char_count <= 1 {
                        ui.text_colored(*c0, name_part);
                    } else {
                        profile_span!("render_name_gradient");
                        let n = char_count as f32;
                        let mut buf = [0u8; 4];
                        for (i, ch) in name_part.chars().enumerate() {
                            if i > 0 {
                                ui.same_line_with_spacing(0.0, 0.0);
                            }
                            let t = i as f32 / (n - 1.0);
                            let lerped = [
                                c0[0] + (c1[0] - c0[0]) * t,
                                c0[1] + (c1[1] - c0[1]) * t,
                                c0[2] + (c1[2] - c0[2]) * t,
                                c0[3] + (c1[3] - c0[3]) * t,
                            ];
                            let s = ch.encode_utf8(&mut buf);
                            ui.text_colored(lerped, s);
                        }
                    }
                }
                None => {
                    ui.text_colored(color, name_part);
                }
            }
        }

        // Gap (right-aligned within gap column, color-coded)
        if let Some(gt) = gap_text {
            let gap_color = match computed_gap_ms {
                Some(ms) if ms < 0 => c.success,
                Some(ms) if ms > 0 => c.danger,
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
        &mut self,
        ui: &hudhook::imgui::Ui,
        max_width: f32,
        bufs: &mut RenderBuffers,
    ) {
        profile_span!("render_leaderboard");
        if self.participants().is_empty() {
            ui.text_disabled("No participants");
            return;
        }

        let buf_left = &mut bufs.buf_left;
        let buf_footer = &mut bufs.buf_footer;
        self.refresh_leaderboard_cache(ui, max_width);
        let participants = self.participants();
        let cache = &self.leaderboard_cache;

        let mut emit_row =
            |idx: usize, rank: usize, is_self: bool, p: &crate::core::protocol::ParticipantInfo| {
                let row = &cache.rows[idx];
                self.render_participant_row(
                    ui,
                    p,
                    rank,
                    max_width,
                    cache.spacing,
                    is_self,
                    cache.max_gap_width,
                    cache.max_right_width,
                    &row.right_text,
                    row.gap_text.as_deref(),
                    row.computed_gap_ms,
                    buf_left,
                    row.name_color.as_ref(),
                );
            };

        // Render top rows
        for (i, p) in participants.iter().take(cache.top_count).enumerate() {
            emit_row(i, i + 1, cache.my_index == Some(i), p);
        }

        // Anchor: separator + self row
        if cache.need_anchor {
            if let Some(idx) = cache.my_index {
                ui.text_disabled("  \u{00B7}\u{00B7}\u{00B7}");
                emit_row(idx, idx + 1, true, &participants[idx]);
            }
        }

        // "+ N more" footer
        if cache.footer_more > 0 {
            buf_footer.clear();
            write!(buf_footer, "  + {} more", cache.footer_more).ok();
            ui.text_disabled(buf_footer);
        }
    }

    fn refresh_leaderboard_cache(&mut self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let local_igt_bucket = self
            .read_igt()
            .map(|igt| igt / LEADERBOARD_REFRESH_INTERVAL_MS);
        let should_refresh = self.leaderboard_cache.version != self.leaderboard_version
            || self.leaderboard_cache.local_igt_bucket != local_igt_bucket
            || (self.leaderboard_cache.max_width - max_width).abs() > f32::EPSILON;
        if !should_refresh {
            return;
        }
        profile_span!("refresh_leaderboard_cache");

        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let race_finished = self
            .race_info()
            .is_some_and(|r| r.status.as_str() == "finished");
        let spacing = ui.calc_text_size(" ")[0];
        // Access fields directly (not through &self methods) so the borrow
        // checker can see they are disjoint from leaderboard_cache.
        let participants = &self.race_state.participants;
        let leader_splits = self.race_state.leader_splits.as_ref();
        let local_igt = self.read_igt().map(|v| v as i32);
        let my_id = self.my_participant_id().cloned();

        let leader_igt_ms = participants
            .first()
            .filter(|p| p.status == "playing" || p.status == "finished")
            .map(|p| {
                if my_id.as_deref().is_some_and(|id| id == p.id) {
                    local_igt.unwrap_or(p.igt_ms)
                } else {
                    p.igt_ms
                }
            })
            .unwrap_or(0);
        let has_leader = leader_splits.is_some_and(|s| !s.is_empty())
            || participants.first().is_some_and(|p| p.status == "finished");
        let leader_finished = participants.first().is_some_and(|p| p.status == "finished");

        let cache = &mut self.leaderboard_cache;
        cache.rows.clear();
        cache.max_gap_width = 0.0;
        cache.max_right_width = 0.0;

        profile_span!("leaderboard_rows");
        for (i, p) in participants.iter().enumerate() {
            let computed_gap_ms = if !has_leader {
                None
            } else if p.status == "finished" || race_finished {
                p.gap_ms
            } else {
                let igt = if my_id.as_deref().is_some_and(|id| id == p.id) {
                    local_igt.unwrap_or(p.igt_ms)
                } else {
                    p.igt_ms
                };
                leader_splits.and_then(|splits| {
                    crate::core::compute_gap(
                        igt,
                        p.current_layer,
                        p.layer_entry_igt,
                        splits,
                        i == 0,
                        &p.status,
                        leader_igt_ms,
                        leader_finished,
                    )
                })
            };

            let mut row = LeaderboardRowCache::default();
            write_participant_right_text(
                &mut row.right_text,
                &p.status,
                p.current_layer,
                total_layers,
                p.igt_ms,
            );
            cache.max_right_width = cache
                .max_right_width
                .max(ui.calc_text_size(&row.right_text)[0]);

            if let Some(gap_ms) = computed_gap_ms {
                let mut gap_text = String::with_capacity(16);
                crate::core::format_gap_into(&mut gap_text, gap_ms);
                cache.max_gap_width = cache.max_gap_width.max(ui.calc_text_size(&gap_text)[0]);
                row.gap_text = Some(gap_text);
            }
            row.computed_gap_ms = computed_gap_ms;
            row.name_color = p.name_template.as_ref().and_then(|nt| {
                if let Some((a, b)) = nt.gradient.as_ref() {
                    Some(crate::dll::tracker::ResolvedNameColor::Gradient(
                        crate::core::parse_hex_color(a, 1.0),
                        crate::core::parse_hex_color(b, 1.0),
                    ))
                } else if let Some(c) = nt.color.as_ref() {
                    Some(crate::dll::tracker::ResolvedNameColor::Solid(
                        crate::core::parse_hex_color(c, 1.0),
                    ))
                } else {
                    None
                }
            });
            cache.rows.push(row);
        }

        cache.my_index = self.my_participant_index;
        let layout = crate::core::compute_leaderboard_layout(participants.len(), cache.my_index);
        cache.need_anchor = layout.need_anchor;
        cache.top_count = layout.top_count;
        cache.footer_more = layout.footer_more;
        cache.version = self.leaderboard_version;
        cache.local_igt_bucket = local_igt_bucket;
        cache.max_width = max_width;
        cache.spacing = spacing;
    }

    /// Status message: persistent danger banner for permanent errors,
    /// temporary gold banner otherwise.
    fn render_status_message(&self, ui: &hudhook::imgui::Ui) {
        let c = &self.cached_colors;
        // Permanent errors are always visible
        if let Some(ref err) = self.permanent_error {
            ui.separator();
            ui.text_colored(c.danger, err);
            return;
        }
        // Temporary status messages (auto-dismiss)
        if let Some(status) = self.get_status() {
            ui.separator();
            ui.text_colored(c.gold, status);
        }
    }

    fn render_debug(&self, ui: &hudhook::imgui::Ui) {
        let c = &self.cached_colors;
        ui.text_colored(c.gold, "Debug");

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
            c.success
        } else {
            c.danger
        };
        ui.text_colored(status_color, &debug.flag_reader_status);

        // Vanilla flag sanity check (category 0 should always exist)
        let (sanity_color, sanity_label) = match &debug.vanilla_sanity {
            FlagReadResult::Set => (c.success, "true"),
            FlagReadResult::NotSet => (c.text, "false"),
            FlagReadResult::Unreadable => (c.danger, "None"),
        };
        ui.text("  vanilla 6:");
        ui.same_line();
        ui.text_colored(sanity_color, sanity_label);

        if !debug.sample_reads.is_empty() {
            for (flag_id, result) in &debug.sample_reads {
                let (color, label) = match result {
                    FlagReadResult::Set => (c.success, "true"),
                    FlagReadResult::NotSet => (c.text, "false"),
                    FlagReadResult::Unreadable => (c.danger, "None"),
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

/// hudhook requires at least one ImGui window per frame; this builds an
/// invisible placeholder.
fn build_hidden_window(ui: &hudhook::imgui::Ui) {
    ui.window("##hidden")
        .position([-100.0, -100.0], Condition::Always)
        .size([1.0, 1.0], Condition::Always)
        .no_decoration()
        .build(|| {});
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
