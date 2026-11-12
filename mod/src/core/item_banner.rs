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
}
