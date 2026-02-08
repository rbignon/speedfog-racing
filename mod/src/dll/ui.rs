//! Race UI - ImGui overlay for SpeedFog Racing

use hudhook::imgui::{Condition, StyleColor, WindowFlags};
use hudhook::{ImguiRenderLoop, RenderContext};
use tracing::info;

use super::tracker::RaceTracker;
use super::websocket::ConnectionStatus;

impl ImguiRenderLoop for RaceTracker {
    fn initialize<'a>(
        &'a mut self,
        _ctx: &mut hudhook::imgui::Context,
        _render_context: &'a mut dyn RenderContext,
    ) {
        info!("Race UI initialized");
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

        let [dw, _dh] = ui.io().display_size;
        let window_width = 280.0;

        // Semi-transparent background
        let _bg = ui.push_style_color(StyleColor::WindowBg, [0.08, 0.08, 0.08, 0.85]);

        let flags =
            WindowFlags::NO_TITLE_BAR | WindowFlags::ALWAYS_AUTO_RESIZE | WindowFlags::NO_SCROLLBAR;

        ui.window("SpeedFog Race")
            .position([dw - window_width - 20.0, 20.0], Condition::FirstUseEver)
            .flags(flags)
            .build(|| {
                self.render_header(ui);
                ui.separator();
                self.render_player_status(ui);
                ui.separator();
                self.render_leaderboard(ui);
                if self.show_debug {
                    ui.separator();
                    self.render_debug(ui);
                }
            });
    }
}

impl RaceTracker {
    fn render_header(&self, ui: &hudhook::imgui::Ui) {
        // Connection status dot
        let (color, text) = match self.ws_status() {
            ConnectionStatus::Connected => ([0.0, 1.0, 0.0, 1.0], "●"),
            ConnectionStatus::Connecting | ConnectionStatus::Reconnecting => {
                ([1.0, 0.65, 0.0, 1.0], "●")
            }
            _ => ([1.0, 0.0, 0.0, 1.0], "●"),
        };
        ui.text_colored(color, text);
        ui.same_line();

        // Race name
        if let Some(race) = self.race_info() {
            ui.text(&race.name);
            ui.same_line();
            ui.text_disabled(format!("[{}]", race.status));
        } else {
            ui.text("Connecting...");
        }
    }

    fn render_player_status(&self, ui: &hudhook::imgui::Ui) {
        // Progress
        let progress = self.triggered_count();
        let total = self.total_flags();
        ui.text(format!("Progress: {}/{}", progress, total));

        // IGT
        if let Some(igt_ms) = self.read_igt() {
            let secs = igt_ms / 1000;
            let mins = secs / 60;
            let hours = mins / 60;
            ui.text(format!(
                "IGT: {:02}:{:02}:{:02}",
                hours,
                mins % 60,
                secs % 60
            ));
        }

        // Deaths
        if let Some(deaths) = self.read_deaths() {
            ui.text(format!("Deaths: {}", deaths));
        }
    }

    fn render_leaderboard(&self, ui: &hudhook::imgui::Ui) {
        ui.text("Leaderboard");

        let participants = self.participants();
        if participants.is_empty() {
            ui.text_disabled("No participants");
            return;
        }

        for (i, p) in participants.iter().take(10).enumerate() {
            let name = p
                .twitch_display_name
                .as_deref()
                .unwrap_or(&p.twitch_username);

            let time_str = format_time(p.igt_ms);

            let status_indicator = match p.status.as_str() {
                "finished" => "✓",
                "playing" => "►",
                "ready" => "○",
                _ => "·",
            };

            // Color based on status
            let color = match p.status.as_str() {
                "finished" => [0.5, 1.0, 0.5, 1.0],
                "playing" => [1.0, 1.0, 1.0, 1.0],
                _ => [0.5, 0.5, 0.5, 1.0],
            };

            ui.text_colored(
                color,
                format!(
                    "{:2}. {} {} L{} {}",
                    i + 1,
                    status_indicator,
                    name,
                    p.current_layer,
                    time_str
                ),
            );
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
            ui.text("  –");
        } else {
            for p in participants {
                let name = p
                    .twitch_display_name
                    .as_deref()
                    .unwrap_or(&p.twitch_username);
                let zone = p.current_zone.as_deref().unwrap_or("–");
                ui.text(format!("  {}: {}", name, zone));
            }
        }

        // Last sent message
        ui.text_disabled("Sent:");
        ui.same_line();
        ui.text(debug.last_sent.unwrap_or("–"));

        // Last received message
        ui.text_disabled("Recv:");
        ui.same_line();
        ui.text(debug.last_received.unwrap_or("–"));
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
