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

        // Load death icon texture
        match DeathIcon::load(render_context) {
            Ok(icon) => {
                info!("Loaded death icon texture");
                self.death_icon = Some(icon);
            }
            Err(e) => {
                error!(error = %e, "Failed to load death icon");
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
                if !self.config.server.training {
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

    /// Compact 2-line player status:
    /// Line 1: `● RaceName               HH:MM:SS` (IGT in red)
    /// Line 2: `  tier X, previously Y   [☠]N  X/Y` (yellow + green)
    fn render_player_status(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let red = [1.0, 0.0, 0.0, 1.0];
        let yellow = [1.0, 1.0, 0.0, 1.0];
        let green = [0.0, 1.0, 0.0, 1.0];

        // --- Line 1: connection dot + race name (left), local IGT in red (right) ---
        let (dot_color, _) = match self.ws_status() {
            ConnectionStatus::Connected => (green, "connected"),
            ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => {
                ([1.0, 0.65, 0.0, 1.0], "connecting")
            }
            _ => (red, "disconnected"),
        };

        // Right side: local IGT (red)
        let igt_str = if let Some(igt_ms) = self.read_igt() {
            format_time_u32(igt_ms)
        } else {
            "--:--:--".to_string()
        };
        let igt_width = ui.calc_text_size(&igt_str)[0];

        // Left side: dot + race name
        let dot_str = "\u{25CF} "; // "● "
        let dot_width = ui.calc_text_size(dot_str)[0];
        let gap = ui.calc_text_size(" ")[0];
        let name_max = max_width - igt_width - gap - dot_width;

        ui.text_colored(dot_color, dot_str);
        ui.same_line_with_spacing(0.0, 0.0);

        let name_text = if let Some(race) = self.race_info() {
            let display_name = if self.config.server.training {
                "Training"
            } else {
                race.name.as_str()
            };
            display_name.to_string()
        } else {
            "Connecting...".to_string()
        };
        let truncated = truncate_to_width(ui, &name_text, name_max);
        ui.text(&truncated);

        // Right-align IGT (red)
        ui.same_line_with_pos(max_width - igt_width);
        ui.text_colored(red, &igt_str);

        // --- Line 2: tier info (left, yellow), deaths + progress (right, green) ---
        let me = self.my_participant();
        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
        let zone = self.current_zone_info();

        // Right side: death icon + count + "  X/Y" progress
        let deaths = self.read_deaths().unwrap_or(0);
        let layer = me.map(|p| p.current_layer).unwrap_or(0);
        let death_str = format!("{}", deaths);
        let display_layer = (layer + 1).min(total_layers);
        let progress_str = format!("  {}/{}", display_layer, total_layers);
        let font_height = ui.text_line_height();
        let icon_size = font_height;
        let icon_gap = 2.0;
        let right_total = if self.death_icon.is_some() {
            icon_size
                + icon_gap
                + ui.calc_text_size(&death_str)[0]
                + ui.calc_text_size(&progress_str)[0]
        } else {
            ui.calc_text_size(&format!("{}{}", death_str, progress_str))[0]
        };

        // Left side: tier info (yellow) or zone name (white) or "--"
        let left_text = if let Some(z) = zone {
            if let Some(t) = z.tier {
                if let Some(ot) = z.original_tier.filter(|&ot| ot != t) {
                    format!("  tier {}, previously {}", t, ot)
                } else {
                    format!("  tier {}", t)
                }
            } else {
                format!("  {}", z.display_name)
            }
        } else if let Some(tier) = me.and_then(|p| p.current_layer_tier) {
            format!("  tier {}", tier)
        } else {
            "  --".to_string()
        };
        let has_tier = zone.is_some_and(|z| z.tier.is_some())
            || me.is_some_and(|p| p.current_layer_tier.is_some());
        let left_color = if has_tier {
            yellow
        } else {
            self.cached_colors.text
        };

        let left_max = max_width - right_total - gap;
        let left_truncated = truncate_to_width(ui, &left_text, left_max);
        ui.text_colored(left_color, &left_truncated);

        // Right-align: death icon + count + progress (green)
        ui.same_line_with_pos(max_width - right_total);
        if let Some(ref icon) = self.death_icon {
            Image::new(icon.texture_id(), [icon_size, icon_size]).build(ui);
            ui.same_line_with_spacing(0.0, icon_gap);
        }
        ui.text_colored(green, &death_str);
        ui.same_line_with_spacing(0.0, 0.0);
        ui.text_colored(green, &progress_str);
    }

    /// Render exit list from zone_update:
    /// ```text
    /// → Soldier of Godrick front
    ///   ???
    /// → Stranded Graveyard first door
    ///   Ruin-Strewn Precipice          (green)
    /// ```
    fn render_exits(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        let zone = match self.current_zone_info() {
            Some(z) if !z.exits.is_empty() => z,
            _ => return,
        };

        let green = [0.0, 1.0, 0.0, 1.0];

        for exit in &zone.exits {
            // Arrow + fog gate text
            let arrow_text = format!("\u{2192} {}", exit.text);
            let truncated = truncate_to_width(ui, &arrow_text, max_width);
            ui.text_disabled(&truncated);

            // Destination: "???" if undiscovered, green name if discovered
            if exit.discovered {
                let dest = format!("  {}", exit.to_name);
                let truncated = truncate_to_width(ui, &dest, max_width);
                ui.text_colored(green, &truncated);
            } else {
                ui.text_disabled("  ???");
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
                _ => format!("{}/{}", p.current_layer, total_layers),
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
