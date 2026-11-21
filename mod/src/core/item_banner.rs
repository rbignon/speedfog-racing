//! Geometry and text of the race item overlay: the top-centre banner and the
//! seconds-left column of the reminder rows.
//!
//! Everything derives from the display size, so a resolution change is picked
//! up by the next frame. Proportions are fractions of the screen width (the
//! banner block hangs from a fraction of its height).

use std::fmt::Write;
use std::time::Duration;

/// Banner block top, as a fraction of the display height (under the compass).
const BLOCK_TOP: f32 = 0.13;
/// Backdrop gradient reach from the top edge, as a fraction of the height.
const GRADIENT_REACH: f32 = 0.48;
/// Backdrop alpha at the top edge, over the page ground colour.
pub const GRADIENT_ALPHA: f32 = 0.78;
const ICON: f32 = 0.075;
const TITLE: f32 = 0.034;
const LINE: f32 = 0.016;
const DETAIL: f32 = 0.012;
const TITLE_GAP: f32 = 0.004;
const LINE_GAP: f32 = 0.005;
const DETAIL_GAP: f32 = 0.002;
/// Letter spacing of the title, in em.
const TITLE_TRACKING_EM: f32 = 0.08;
/// Body faces are laid out at this multiple of their pixel size per line.
const BODY_LINE_HEIGHT: f32 = 1.25;

/// Pixel sizes and vertical positions of the banner, for one display size.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BannerLayout {
    pub center_x: f32,
    pub gradient_height: f32,
    pub icon_size: f32,
    pub icon_y: f32,
    pub title_px: f32,
    pub title_y: f32,
    /// Extra advance after each title glyph.
    pub title_tracking: f32,
    pub line_px: f32,
    pub line_y: f32,
    pub detail_px: f32,
    pub detail_y: f32,
    /// Offset of the 1 px dark shadow under each text and the icon.
    pub shadow: f32,
}

pub fn banner_layout(display: [f32; 2]) -> BannerLayout {
    let [dw, dh] = display;
    let icon_size = ICON * dw;
    let icon_y = BLOCK_TOP * dh;
    let title_px = TITLE * dw;
    let title_y = icon_y + icon_size + TITLE_GAP * dw;
    let line_px = LINE * dw;
    let line_y = title_y + title_px + LINE_GAP * dw;
    let detail_px = DETAIL * dw;
    let detail_y = line_y + line_px * BODY_LINE_HEIGHT + DETAIL_GAP * dw;
    BannerLayout {
        center_x: dw * 0.5,
        gradient_height: GRADIENT_REACH * dh,
        icon_size,
        icon_y,
        title_px,
        title_y,
        title_tracking: TITLE_TRACKING_EM * title_px,
        line_px,
        line_y,
        detail_px,
        detail_y,
        shadow: 1.0,
    }
}

/// Menu rows are this many line heights tall.
const ROW_HEIGHT: f32 = 1.6;
/// Width of the menu, as a fraction of the sizing width.
const MENU_WIDTH: f32 = 0.328;
/// Widest text a relay block draws, as a fraction of the sizing width: the
/// limit the drawing cuts names and zones to with `truncate_to_width`.
const TEXT_MAX_WIDTH: f32 = 0.7;
/// The hold bar's height: a fraction of the display height, at least 3 px.
const BAR_HEIGHT: f32 = 0.0042;
/// The sizing width never exceeds this many widths per height, so an
/// ultrawide keeps the proportions of a 16:9 screen of its height (the
/// stack of title, rows and detail would otherwise outgrow the gradient).
const SIZING_ASPECT: f32 = 16.0 / 9.0;

/// Pixel sizes and vertical positions of the relay block (the waiting
/// banner and the holder's menu), for one display size. It stacks as the
/// item banner does, minus the icon: the title hangs from `BLOCK_TOP`, then
/// either the line or the menu rows start at `line_y`, then the detail.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RelayBlockLayout {
    pub center_x: f32,
    pub gradient_height: f32,
    pub title_px: f32,
    pub title_y: f32,
    pub title_tracking: f32,
    pub line_px: f32,
    pub line_y: f32,
    pub detail_px: f32,
    pub detail_y: f32,
    /// Height of one menu row; row `i` starts at `line_y + i * row_height`.
    pub row_height: f32,
    pub menu_width: f32,
    /// Widest a text of the block may draw; longer is cut to it.
    pub text_max_width: f32,
    pub bar_height: f32,
    pub shadow: f32,
}

/// The block's layout with `rows` menu rows (0 for the waiting banner).
pub fn relay_block_layout(display: [f32; 2], rows: usize) -> RelayBlockLayout {
    let [dw, dh] = display;
    let unit = dw.min(dh * SIZING_ASPECT);
    let title_px = TITLE * unit;
    let title_y = BLOCK_TOP * dh;
    let line_px = LINE * unit;
    let line_y = title_y + title_px + LINE_GAP * unit;
    let row_height = ROW_HEIGHT * line_px;
    let body = if rows == 0 {
        line_px * BODY_LINE_HEIGHT
    } else {
        rows as f32 * row_height
    };
    let detail_px = DETAIL * unit;
    RelayBlockLayout {
        center_x: dw * 0.5,
        gradient_height: GRADIENT_REACH * dh,
        title_px,
        title_y,
        title_tracking: TITLE_TRACKING_EM * title_px,
        line_px,
        line_y,
        detail_px,
        detail_y: line_y + body + DETAIL_GAP * unit,
        row_height,
        menu_width: MENU_WIDTH * unit,
        text_max_width: TEXT_MAX_WIDTH * unit,
        bar_height: (BAR_HEIGHT * dh).max(3.0),
        shadow: 1.0,
    }
}

/// Measured widths of the texts of a block, in pixels (the drawing asks
/// ImGui; the layout cannot).
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct RelayBlockWidths {
    pub title: f32,
    pub line: f32,
    pub detail: f32,
    /// The widest menu row's text, 0 without a menu.
    pub rows: f32,
}

/// The block's bounding box on screen: left, top, right, bottom. Every text
/// is clamped to `text_max_width` (what the drawing cuts it to), the menu is
/// at least `menu_width` wide, the box is centred and never leaves the
/// display.
pub fn relay_block_bounds(
    layout: &RelayBlockLayout,
    display: [f32; 2],
    rows: usize,
    widths: RelayBlockWidths,
) -> [f32; 4] {
    let clamp = |w: f32| w.clamp(0.0, layout.text_max_width);
    let mut half = clamp(widths.title)
        .max(clamp(widths.line))
        .max(clamp(widths.detail))
        .max(clamp(widths.rows))
        * 0.5;
    if rows > 0 {
        half = half.max(layout.menu_width * 0.5);
    }
    half = half.min(display[0] * 0.5);
    let bottom = layout.detail_y + layout.detail_px;
    [
        layout.center_x - half,
        layout.title_y,
        layout.center_x + half,
        bottom,
    ]
}

/// Write the time left of a reminder as whole seconds, rounded up so a row
/// never reads `0s` while it is still on screen.
pub fn write_seconds_left(buf: &mut String, left: Duration) {
    let secs = left.as_millis().div_ceil(1000);
    write!(buf, "{}s", secs).ok();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn banner_stacks_top_to_bottom_without_overlap() {
        for display in [[1280.0, 720.0], [1920.0, 1080.0], [3840.0, 2160.0]] {
            let l = banner_layout(display);
            assert!(l.icon_y + l.icon_size <= l.title_y);
            assert!(l.title_y + l.title_px <= l.line_y);
            assert!(l.line_y + l.line_px <= l.detail_y);
            assert!(l.detail_y + l.detail_px < l.gradient_height);
        }
    }

    #[test]
    fn banner_scales_with_the_display() {
        let hd = banner_layout([1920.0, 1080.0]);
        let uhd = banner_layout([3840.0, 2160.0]);
        assert!((uhd.title_px - 2.0 * hd.title_px).abs() < 0.01);
        assert!((uhd.detail_y - 2.0 * hd.detail_y).abs() < 0.01);
        assert!((hd.center_x - 960.0).abs() < f32::EPSILON);
    }

    #[test]
    fn seconds_left_round_up() {
        let mut buf = String::new();
        for (ms, want) in [(14_200, "15s"), (100, "1s"), (3_000, "3s"), (15_000, "15s")] {
            buf.clear();
            write_seconds_left(&mut buf, Duration::from_millis(ms));
            assert_eq!(buf, want);
        }
    }

    #[test]
    fn the_relay_block_stacks_without_overlap() {
        for display in [
            [1280.0, 720.0],
            [1920.0, 1080.0],
            [2560.0, 1440.0],
            [3440.0, 1440.0],
            [3840.0, 2160.0],
        ] {
            for rows in 0..=5 {
                let l = relay_block_layout(display, rows);
                assert!(l.title_y + l.title_px <= l.line_y, "{display:?} {rows}");
                let body = if rows == 0 {
                    l.line_px
                } else {
                    rows as f32 * l.row_height
                };
                assert!(l.line_y + body <= l.detail_y, "{display:?} {rows}");
                assert!(
                    l.detail_y + l.detail_px + l.bar_height < l.gradient_height,
                    "{display:?} {rows}"
                );
                assert_eq!(l.title_y, banner_layout(display).icon_y);
            }
        }
    }

    #[test]
    fn the_relay_block_sizes_follow_the_height_on_an_ultrawide() {
        let wide = relay_block_layout([3440.0, 1440.0], 3);
        let hd = relay_block_layout([2560.0, 1440.0], 3);
        assert_eq!(wide.title_px, hd.title_px);
        assert_eq!(wide.menu_width, hd.menu_width);
        assert_eq!(wide.center_x, 1720.0);
        // A 16:9 display sizes from its width, as the item banner does.
        let l = relay_block_layout([1920.0, 1080.0], 0);
        assert_eq!(l.title_px, banner_layout([1920.0, 1080.0]).title_px);
        assert!((l.menu_width - 0.328 * 1920.0).abs() < 0.01);
        assert!((l.bar_height - 0.0042 * 1080.0).abs() < 0.01);
        assert_eq!(relay_block_layout([320.0, 180.0], 0).bar_height, 3.0);
    }

    #[test]
    fn a_long_text_is_cut_inside_the_display() {
        for display in [
            [1280.0, 720.0],
            [1920.0, 1080.0],
            [2560.0, 1440.0],
            [3440.0, 1440.0],
            [800.0, 800.0],
        ] {
            let l = relay_block_layout(display, 4);
            let b = relay_block_bounds(
                &l,
                display,
                4,
                RelayBlockWidths {
                    title: 1e6,
                    line: 1e6,
                    detail: 1e6,
                    rows: 1e6,
                },
            );
            assert!(b[0] >= 0.0 && b[2] <= display[0], "{display:?} {b:?}");
            assert!((b[2] - b[0] - l.text_max_width).abs() < 0.01);
            assert!(b[1] >= l.title_y && b[3] < l.gradient_height);
            // Narrow text still gets the menu's width.
            let b = relay_block_bounds(&l, display, 4, RelayBlockWidths::default());
            assert!((b[2] - b[0] - l.menu_width).abs() < 0.01);
            assert!((b[0] + b[2]) * 0.5 - l.center_x < 0.01);
        }
    }
}
