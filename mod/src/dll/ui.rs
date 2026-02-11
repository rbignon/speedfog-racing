//! Race UI - ImGui overlay for SpeedFog Racing

use hudhook::imgui::{Condition, FontConfig, FontGlyphRanges, FontSource, StyleColor, WindowFlags};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::info;

use crate::core::color::parse_hex_color;

use crate::eldenring::FlagReaderStatus;

use super::tracker::{FlagReadResult, RaceTracker};
use super::websocket::ConnectionStatus;

impl ImguiRenderLoop for RaceTracker {
    fn initialize<'a>(
        &'a mut self,
        ctx: &mut hudhook::imgui::Context,
        _render_context: &'a mut dyn RenderContext,
    ) {
        if let Some(ref font_data) = self.font_data {
            let font_size = self.config.overlay.font_size;

            // Glyph ranges: Basic Latin + Punctuation + Box/Geometric + Arrows + Dagger
            let glyph_ranges = FontGlyphRanges::from_slice(&[
                0x0020, 0x00FF, // Basic Latin + Latin Supplement
                0x2000, 0x206F, // General Punctuation (†)
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

        let s = &self.config.overlay;

        // Parse colors from config
        let bg_color = parse_hex_color(&s.background_color, s.background_opacity);
        let text_color = parse_hex_color(&s.text_color, 1.0);
        let text_disabled_color = parse_hex_color(&s.text_disabled_color, 1.0);
        let border_color = if s.show_border {
            parse_hex_color(&s.border_color, 1.0)
        } else {
            [0.0, 0.0, 0.0, 0.0]
        };

        // Push style colors (auto-popped when tokens drop)
        let _bg_token = ui.push_style_color(StyleColor::WindowBg, bg_color);
        let _text_token = ui.push_style_color(StyleColor::Text, text_color);
        let _text_disabled_token =
            ui.push_style_color(StyleColor::TextDisabled, text_disabled_color);
        let _border_token = ui.push_style_color(StyleColor::Border, border_color);

        let [dw, _dh] = ui.io().display_size;
        let scale = s.font_size / 16.0;
        let max_width = 320.0 * scale;

        let flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        ui.window("SpeedFog Race")
            .position(
                [dw - max_width - s.position_offset_x, s.position_offset_y],
                Condition::FirstUseEver,
            )
            .flags(flags)
            .build(|| {
                self.render_player_status(ui, max_width);
                ui.separator();
                self.render_leaderboard(ui, max_width);
                if self.show_debug {
                    ui.separator();
                    self.render_debug(ui);
                }
            });
    }
}

impl RaceTracker {
    /// Compact 2-line player status:
    /// Line 1: `● RaceName [status]           HH:MM:SS`
    /// Line 2: `  Tier X                   †N    X/Y`
    fn render_player_status(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
        // --- Line 1: connection dot + race name + status (left), local IGT (right) ---
        let (dot_color, _) = match self.ws_status() {
            ConnectionStatus::Connected => ([0.0, 1.0, 0.0, 1.0], "connected"),
            ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => {
                ([1.0, 0.65, 0.0, 1.0], "connecting")
            }
            _ => ([1.0, 0.0, 0.0, 1.0], "disconnected"),
        };

        // Right side: local IGT
        let igt_str = if let Some(igt_ms) = self.read_igt() {
            format_time_u32(igt_ms)
        } else {
            "--:--:--".to_string()
        };
        let igt_width = ui.calc_text_size(&igt_str)[0];

        // Left side: dot + race name + [status]
        let dot_str = "\u{25CF} "; // "● "
        let dot_width = ui.calc_text_size(dot_str)[0];
        let gap = ui.calc_text_size(" ")[0];
        let name_max = max_width - igt_width - gap - dot_width;

        ui.text_colored(dot_color, dot_str);
        ui.same_line_with_spacing(0.0, 0.0);

        let name_text = if let Some(race) = self.race_info() {
            format!("{} [{}]", race.name, race.status)
        } else {
            "Connecting...".to_string()
        };
        let truncated = truncate_to_width(ui, &name_text, name_max);
        ui.text(&truncated);

        // Right-align IGT
        ui.same_line_with_pos(max_width - igt_width);
        ui.text(&igt_str);

        // --- Line 2: tier (left), deaths + progress (right) ---
        let me = self.my_participant();
        let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);

        // Right side: "†N  X/Y" — use local game memory for instant updates
        let deaths = self.read_deaths().unwrap_or(0);
        let layer = me.map(|p| p.current_layer).unwrap_or(0);
        let right_text = format!("\u{2020}{}  {}/{}", deaths, layer, total_layers);
        let right_width = ui.calc_text_size(&right_text)[0];

        // Left side: "  Tier X"
        let left_text = if let Some(tier) = me.and_then(|p| p.current_layer_tier) {
            format!("  Tier {}", tier)
        } else {
            "  --".to_string()
        };
        ui.text(&left_text);

        // Right-align deaths + progress
        ui.same_line_with_pos(max_width - right_width);
        ui.text(&right_text);
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
                "finished" => [0.5, 1.0, 0.5, 1.0],
                "playing" => parse_hex_color(&self.config.overlay.text_color, 1.0),
                "ready" => [1.0, 0.65, 0.0, 1.0],
                _ => parse_hex_color(&self.config.overlay.text_disabled_color, 1.0),
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
            [0.5, 1.0, 0.5, 1.0] // green
        } else {
            [1.0, 0.3, 0.3, 1.0] // red
        };
        ui.text_colored(status_color, debug.flag_reader_status.to_string());

        // Vanilla flag sanity check (category 0 should always exist)
        let (sanity_color, sanity_label) = match &debug.vanilla_sanity {
            FlagReadResult::Set => ([0.5, 1.0, 0.5, 1.0], "true"),
            FlagReadResult::NotSet => (
                parse_hex_color(&self.config.overlay.text_color, 1.0),
                "false",
            ),
            FlagReadResult::Unreadable => ([1.0, 0.3, 0.3, 1.0], "None"),
        };
        ui.text("  vanilla 6:");
        ui.same_line();
        ui.text_colored(sanity_color, sanity_label);

        if !debug.sample_reads.is_empty() {
            for (flag_id, result) in &debug.sample_reads {
                let (color, label) = match result {
                    FlagReadResult::Set => ([0.5, 1.0, 0.5, 1.0], "true"),
                    FlagReadResult::NotSet => (
                        parse_hex_color(&self.config.overlay.text_color, 1.0),
                        "false",
                    ),
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

/// Truncate text to fit within `max_width` pixels, adding "…" if needed.
fn truncate_to_width(ui: &hudhook::imgui::Ui, text: &str, max_width: f32) -> String {
    let width = ui.calc_text_size(text)[0];
    if width <= max_width {
        return text.to_string();
    }

    let ellipsis = "\u{2026}"; // …
    let ellipsis_width = ui.calc_text_size(ellipsis)[0];
    let target_width = max_width - ellipsis_width;
    if target_width <= 0.0 {
        return ellipsis.to_string();
    }

    // Binary search for the longest prefix that fits
    let chars: Vec<char> = text.chars().collect();
    let mut low = 0usize;
    let mut high = chars.len();
    while low < high {
        let mid = (low + high + 1) / 2;
        let prefix: String = chars[..mid].iter().collect();
        if ui.calc_text_size(&prefix)[0] <= target_width {
            low = mid;
        } else {
            high = mid - 1;
        }
    }

    let prefix: String = chars[..low].iter().collect();
    format!("{}{}", prefix, ellipsis)
}
