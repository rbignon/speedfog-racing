//! Race UI - ImGui overlay for SpeedFog Racing

use std::borrow::Cow;
use std::time::Duration;

use hudhook::imgui::{
    Condition, FontConfig, FontGlyphRanges, FontSource, Image, StyleColor, WindowFlags,
};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::{error, info};

use super::death_icon::DeathIcon;

use crate::eldenring::FlagReaderStatus;

use super::tracker::{FlagReadResult, RaceTracker};
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
                self.render_state_banner(ui);
                self.render_seed_mismatch_warning(ui);
                self.render_player_status(ui, max_width);
                self.render_exits(ui, max_width);
                if !self.config.server.training && self.show_leaderboard {
                    ui.separator();
                    self.render_leaderboard(ui, max_width);
                }
                self.render_status_message(ui);
                if self.show_debug {
                    ui.separator();
                    self.render_debug(ui);
                }
            });
    }
}

impl RaceTracker {
    /// Render state banner above player status.
    /// - SETUP: orange "WAITING FOR START"
    /// - RUNNING (first 3s): green "GO!"
    /// - FINISHED: green "RACE FINISHED"
    /// - RUNNING (after 3s): nothing
    fn render_state_banner(&self, ui: &hudhook::imgui::Ui) {
        let orange = [1.0, 0.75, 0.0, 1.0];
        let green = [0.0, 1.0, 0.0, 1.0];

        if let Some(race) = self.race_info() {
            match race.status.as_str() {
                "setup" => {
                    ui.text_colored(orange, "WAITING FOR START");
                }
                "running" => {
                    if let Some(started_at) = self.race_state.race_started_at {
                        if started_at.elapsed() < Duration::from_secs(3) {
                            ui.text_colored(green, "GO!");
                        }
                    }
                }
                "finished" => {
                    ui.text_colored(green, "RACE FINISHED");
                }
                _ => {}
            }
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
    /// Line 1: `● RaceName               HH:MM:SS` (name dimmed, IGT in blue)
    /// Line 2: `  ZoneName                    X/Y` (X yellow→green on finish, /Y white)
    /// Line 3: `  tier X, previously Y   [☠]N`     (tier yellow, deaths white)
    fn render_player_status(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let blue = [0.4, 0.6, 1.0, 1.0];
        let yellow = [1.0, 1.0, 0.0, 1.0];
        let green = [0.0, 1.0, 0.0, 1.0];

        // --- Line 1: connection dot + race name (left), local IGT in blue (right) ---
        let dot_color = match self.ws_status() {
            ConnectionStatus::Connected => green,
            ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => [1.0, 0.65, 0.0, 1.0],
            _ => [1.0, 0.0, 0.0, 1.0],
        };

        // When player has finished, show server-frozen IGT (accurate finish time).
        // When race ended but player didn't finish, show locally captured game IGT
        // (the mod's participant igt_ms from leaderboard_update is stale).
        let igt_str = if self.am_i_finished() {
            if let Some(me) = self.my_participant().filter(|p| p.igt_ms > 0) {
                format_time_u32(me.igt_ms as u32)
            } else {
                "--:--:--".to_string()
            }
        } else if let Some(frozen) = self.frozen_igt_ms {
            format_time_u32(frozen)
        } else if !self.is_race_running() {
            // Race finished but no frozen IGT captured (shouldn't happen normally)
            "--:--:--".to_string()
        } else if let Some(igt_ms) = self.read_igt() {
            format_time_u32(igt_ms)
        } else {
            "--:--:--".to_string()
        };
        let igt_width = ui.calc_text_size(&igt_str)[0];

        let dot_str = "\u{25CF} "; // "● "
        let dot_width = ui.calc_text_size(dot_str)[0];
        let gap = ui.calc_text_size(" ")[0];
        let name_max = max_width - igt_width - gap - dot_width;

        ui.text_colored(dot_color, dot_str);
        ui.same_line_with_spacing(0.0, 0.0);

        let name_text = if let Some(race) = self.race_info() {
            race.name.to_string()
        } else {
            "Connecting...".to_string()
        };
        let truncated = truncate_to_width(ui, &name_text, name_max);
        ui.text_colored(self.cached_colors.text_disabled, &truncated);

        ui.same_line_with_pos(max_width - igt_width);
        ui.text_colored(blue, &igt_str);

        // --- Line 2: zone name (left, white), progress X/Y (right, X=yellow/green Y=white) ---
        let me = self.my_participant();
        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let zone = self.current_zone_info();

        let layer = me.map(|p| p.current_layer).unwrap_or(0);
        let display_layer = (layer + 1).min(total_layers);
        let current_str = format!("{}", display_layer);
        let sep_str = format!("/{}", total_layers);
        let progress_width = ui.calc_text_size(&current_str)[0] + ui.calc_text_size(&sep_str)[0];
        let progress_color = if self.am_i_finished() { green } else { yellow };

        let zone_text = if let Some(z) = zone {
            format!("  {}", z.display_name)
        } else {
            String::new()
        };
        let zone_max = max_width - progress_width - gap;
        let zone_truncated = truncate_to_width(ui, &zone_text, zone_max);
        ui.text(&zone_truncated);

        ui.same_line_with_pos(max_width - progress_width);
        ui.text_colored(progress_color, &current_str);
        ui.same_line_with_spacing(0.0, 0.0);
        ui.text_colored(self.cached_colors.text, &sep_str);

        // --- Line 3: tier info (left, yellow), death icon + count (right, white) ---
        let deaths = self.read_deaths().unwrap_or(0);
        let death_str = format!("{}", deaths);
        let font_height = ui.text_line_height();
        let icon_size = font_height;
        let icon_gap = 2.0;
        let right_total = if self.death_icon.is_some() {
            icon_size + icon_gap + ui.calc_text_size(&death_str)[0]
        } else {
            ui.calc_text_size(&death_str)[0]
        };

        let tier_text = if let Some(z) = zone {
            if let Some(t) = z.tier {
                if let Some(ot) = z.original_tier.filter(|&ot| ot != t) {
                    format!("  tier {}, previously {}", t, ot)
                } else {
                    format!("  tier {}", t)
                }
            } else {
                String::new()
            }
        } else if let Some(tier) = me.and_then(|p| p.current_layer_tier) {
            format!("  tier {}", tier)
        } else {
            String::new()
        };
        let has_tier = zone.is_some_and(|z| z.tier.is_some())
            || me.is_some_and(|p| p.current_layer_tier.is_some());
        let tier_color = if has_tier {
            yellow
        } else {
            self.cached_colors.text
        };

        let tier_max = max_width - right_total - gap;
        let tier_truncated = truncate_to_width(ui, &tier_text, tier_max);
        ui.text_colored(tier_color, &tier_truncated);

        ui.same_line_with_pos(max_width - right_total);
        if let Some(ref icon) = self.death_icon {
            Image::new(icon.texture_id(), [icon_size, icon_size]).build(ui);
            ui.same_line_with_spacing(0.0, icon_gap);
        }
        ui.text_colored(self.cached_colors.text, &death_str);
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
            // Line 1: destination — green if discovered, white "???" if not
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

    /// Leaderboard with color-coded status and right-aligned values:
    /// - ready/playing: `X/Y` right-aligned
    /// - finished: `HH:MM:SS` right-aligned
    fn render_leaderboard(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let participants = self.participants();
        if participants.is_empty() {
            ui.text_disabled("No participants");
            return;
        }

        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let gap = ui.calc_text_size(" ")[0];

        for (i, p) in participants.iter().take(10).enumerate() {
            let name = p
                .twitch_display_name
                .as_deref()
                .unwrap_or(&p.twitch_username);

            // Color: orange=ready, white=playing, green=finished, dim=other
            let color = match p.status.as_str() {
                "finished" => [0.0, 1.0, 0.0, 1.0],
                "playing" => self.cached_colors.text,
                "ready" => [1.0, 0.65, 0.0, 1.0],
                _ => self.cached_colors.text_disabled,
            };

            // Right-aligned value: progress for ready/playing, IGT for finished
            let right_text = match p.status.as_str() {
                "finished" => format_time(p.igt_ms),
                _ => {
                    let display = (p.current_layer + 1).min(total_layers);
                    format!("{}/{}", display, total_layers)
                }
            };
            let right_width = ui.calc_text_size(&right_text)[0];

            // Left: rank + name (truncated to avoid overlap)
            let left_text = format!("{:2}. {}", i + 1, name);
            let left_max = max_width - right_width - gap;
            let truncated = truncate_to_width(ui, &left_text, left_max);
            ui.text_colored(color, &truncated);

            // Right-align value
            ui.same_line_with_pos(max_width - right_width);
            ui.text_colored(color, &right_text);
        }

        if participants.len() > 10 {
            ui.text_disabled(format!("  + {} more", participants.len() - 10));
        }
    }

    /// Temporary status message (yellow text with separator, disappears after 3s).
    fn render_status_message(&self, ui: &hudhook::imgui::Ui) {
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
        let status_color = if matches!(debug.flag_reader_status, FlagReaderStatus::Ok { .. }) {
            [0.0, 1.0, 0.0, 1.0] // green
        } else {
            [1.0, 0.3, 0.3, 1.0] // red
        };
        ui.text_colored(status_color, debug.flag_reader_status.to_string());

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
        ui.text(debug.last_sent.unwrap_or("\u{2013}"));

        // Last received message
        ui.text_disabled("Recv:");
        ui.same_line();
        ui.text(debug.last_received.unwrap_or("\u{2013}"));
    }
}

fn format_time(ms: i32) -> String {
    if ms < 0 {
        return "--:--".to_string();
    }
    let ms = ms as u32;
    let secs = ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    if hours > 0 {
        format!("{}:{:02}:{:02}", hours, mins % 60, secs % 60)
    } else {
        format!("{:02}:{:02}", mins, secs % 60)
    }
}

fn format_time_u32(ms: u32) -> String {
    let secs = ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    format!("{:02}:{:02}:{:02}", hours, mins % 60, secs % 60)
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
            // Single word exceeds max_width — truncate it
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
