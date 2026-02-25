# Leaderboard: Always Show Local Player ("Anchor at Bottom")

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Always show the local player in the overlay leaderboard, even when ranked beyond top 10, with cyan highlight.

**Architecture:** Single function rewrite in `render_leaderboard`. Extract a helper `render_participant_row` to avoid duplicating the row rendering logic between the main loop and the anchored self row.

**Tech Stack:** Rust, hudhook/imgui

---

## Problem

The in-game overlay leaderboard shows the top 10 players. In races with 11+ participants, a player ranked 11th or below never sees themselves on screen.

## Design

### Display Logic

**Case 1 — 10 or fewer participants:** Show all. No change.

**Case 2 — 11+ participants, local player in top 10:** Show top 10 + "+ N more". No change.

**Case 3 — 11+ participants, local player beyond top 10:**

```
 1. PlayerOne           3/8
 2. AnotherGuy          3/8
 ...
 9. SomePlayer          2/8
  ···
14. MyName              1/8
  + 6 more
```

- Show **top 9** (one fewer to make room)
- Separator line `···` (disabled/gray color)
- Local player's row at their **real rank** in the sorted list
- `+ N more` = total - 10 displayed (9 top + 1 self)

### Local Player Highlight

- The local player's name is rendered in **cyan** `[0.0, 1.0, 1.0, 1.0]` regardless of status
- Applies in **all cases** (whether in top 10 or anchored at bottom)
- Cyan is distinct from existing status colors (orange=ready, white=playing, green=finished)

---

## Implementation Plan

### Task 1: Rewrite `render_leaderboard` with anchor + highlight

**Files:**

- Modify: `mod/src/dll/ui.rs:332-380`

#### Step 1: Extract `render_participant_row` helper

Add this method to the `impl RaceTracker` block (before `render_leaderboard`), to render a single participant row. This avoids duplicating row logic for the anchor case.

```rust
/// Render a single leaderboard row: `{rank}. {name}   {progress_or_time}`
/// If `is_self` is true, the name is highlighted in cyan.
fn render_participant_row(
    &self,
    ui: &hudhook::imgui::Ui,
    p: &crate::core::protocol::ParticipantInfo,
    rank: usize,
    total_layers: i32,
    max_width: f32,
    gap: f32,
    is_self: bool,
) {
    let name = p
        .twitch_display_name
        .as_deref()
        .unwrap_or(&p.twitch_username);

    let cyan = [0.0, 1.0, 1.0, 1.0];
    let color = if is_self {
        cyan
    } else {
        match p.status.as_str() {
            "finished" => [0.0, 1.0, 0.0, 1.0],
            "playing" => self.cached_colors.text,
            "ready" => [1.0, 0.65, 0.0, 1.0],
            _ => self.cached_colors.text_disabled,
        }
    };

    let right_text = match p.status.as_str() {
        "finished" => format_time(p.igt_ms),
        _ => {
            let display = (p.current_layer + 1).min(total_layers);
            format!("{}/{}", display, total_layers)
        }
    };
    let right_width = ui.calc_text_size(&right_text)[0];

    let left_text = format!("{:2}. {}", rank, name);
    let left_max = max_width - right_width - gap;
    let truncated = truncate_to_width(ui, &left_text, left_max);
    ui.text_colored(color, &truncated);

    ui.same_line_with_pos(max_width - right_width);
    ui.text_colored(color, &right_text);
}
```

#### Step 2: Rewrite `render_leaderboard` to use the helper + anchor logic

Replace the entire `render_leaderboard` body with:

```rust
fn render_leaderboard(&self, ui: &hudhook::imgui::Ui, max_width: f32) {
    let participants = self.participants();
    if participants.is_empty() {
        ui.text_disabled("No participants");
        return;
    }

    let total_layers = self.seed_info().map(|s| s.total_layers).unwrap_or(0);
    let gap = ui.calc_text_size(" ")[0];

    // Find local player's index in the (pre-sorted) participants list
    let my_index = self.my_participant_id.as_ref().and_then(|my_id| {
        participants.iter().position(|p| &p.id == *my_id)
    });

    // Determine how many top rows to show and whether to anchor self
    let need_anchor = participants.len() > 10
        && my_index.map_or(true, |idx| idx >= 10);
    let top_count = if need_anchor { 9 } else { 10.min(participants.len()) };

    // Render top rows
    for (i, p) in participants.iter().take(top_count).enumerate() {
        let is_self = my_index == Some(i);
        self.render_participant_row(ui, p, i + 1, total_layers, max_width, gap, is_self);
    }

    // Anchor: separator + self row
    if need_anchor {
        if let Some(idx) = my_index {
            ui.text_disabled("  \u{00B7}\u{00B7}\u{00B7}");
            let p = &participants[idx];
            self.render_participant_row(ui, p, idx + 1, total_layers, max_width, gap, true);
        }
    }

    // "+ N more" footer
    let displayed = if need_anchor {
        top_count + if my_index.is_some() { 1 } else { 0 }
    } else {
        top_count
    };
    if participants.len() > displayed {
        ui.text_disabled(format!("  + {} more", participants.len() - displayed));
    }
}
```

#### Step 3: Verify it compiles

Run: `cd mod && cargo check --lib`
Expected: compiles with no errors (warnings OK)

#### Step 4: Commit

```bash
git add mod/src/dll/ui.rs
git commit -m "feat(mod): always show local player in leaderboard overlay

Show top 9 + separator + self at real rank when local player is
beyond top 10. Highlight local player in cyan in all cases."
```

### Task 2: Verify with `cargo test`

#### Step 1: Run existing tests

Run: `cd mod && cargo test`
Expected: all existing tests pass (no UI tests exist, but protocol/core tests must not regress)

#### Step 2: Run clippy

Run: `cd mod && cargo clippy --lib -- -D warnings`
Expected: no errors (warnings promoted to errors)
