//! Fullscreen race countdown: animation state and geometry.
//!
//! The drawing lives in the Windows-only overlay (`dll/ui.rs`); everything
//! that decides *what* to draw is here so it stays testable off Windows.
//! Both entry points are pure functions of the frame's inputs: the elapsed
//! time since the race start message, and the display size. Nothing is
//! cached across frames, so a resolution change (alt-tab, borderless swap)
//! is picked up by the next frame with no atlas rebuild.

use std::time::Duration;

/// Pixel size the countdown face is rasterized at. The drawn size comes from
/// the display height (see [`countdown_layout`]), so the glyphs are scaled at
/// draw time: this size is the ceiling above which scaling starts to soften
/// them, picked to cover 4K (a 4K target lands near 1.1x).
pub const COUNTDOWN_FONT_ATLAS_PX: f32 = 256.0;

/// What a glyph slot draws.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GlyphLabel {
    /// A countdown digit.
    Digit(u32),
    /// The `GO!` label, once the countdown reaches zero.
    Go,
}

/// A glyph with its animation state for this frame.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Glyph {
    pub label: GlyphLabel,
    /// Multiplier on the layout's font size.
    pub scale: f32,
    pub alpha: f32,
}

/// Ring blast expanding out of the countdown ring.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Shockwave {
    /// Multiplier on the layout's ring radius.
    pub radius_factor: f32,
    /// Multiplier on the layout's ring thickness.
    pub thickness_factor: f32,
    pub alpha: f32,
}

/// Everything the overlay draws for one countdown frame.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CountdownFrame {
    /// Glyph entering the screen: the current digit, then `GO!` past zero.
    pub incoming: Glyph,
    /// Glyph leaving the screen during the crossfade that follows a tick.
    pub outgoing: Option<Glyph>,
    /// Share of the ring still filled, 1 at the start and 0 at zero.
    pub ring_fill: f32,
    /// Alpha of the ring itself, so it lifts off screen after `GO!` instead
    /// of blinking out when the last frame is drawn.
    pub ring_alpha: f32,
    pub shockwave: Option<Shockwave>,
    /// Alpha of the screen-edge darkening.
    pub vignette: f32,
    /// Alpha of the race name above the ring.
    pub title_alpha: f32,
}

/// Distance from a drawn glyph's top-left origin down to the optical center
/// of its ink, as a share of the font size.
///
/// ImGui lays text out on the line box, whose empty descender pulls digits
/// above the center they are supposed to sit on. Measured on the embedded
/// Barlow Condensed 600, the only face the countdown draws with: the
/// rasterizer spans ascent to descent (1000 to -200 font units) over the
/// font size, and every glyph drawn here (`0`-`9`, `G`, `O`, `!`) has a flat
/// cap at 700, so the ink centers 350 units above a baseline sitting at
/// 1000: `(1000 - 350) / 1200`. Re-measure if that asset is ever swapped.
pub const DIGIT_INK_CENTER: f32 = 0.541_666_7;

/// The stretch of ring still to draw, as a polyline walk.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RingArc {
    /// Angle of the arc's first point, in radians.
    pub start_angle: f32,
    /// Angle added per segment.
    pub step: f32,
    /// Segments to walk; the arc has one more point than that.
    pub segments: usize,
}

/// Where the countdown's parts sit on screen, in pixels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CountdownLayout {
    pub center: [f32; 2],
    /// Font size for the digits and `GO!`, before the glyph's own scale.
    pub digit_font_px: f32,
    pub title_font_px: f32,
    /// Top of the race name, which the overlay centers horizontally itself.
    pub title_y: f32,
    pub ring_radius: f32,
    pub ring_thickness: f32,
    /// Segments in a full circle of the ring.
    pub ring_segments: usize,
}

/// How long the `GO!` burst stays on screen. Shorter than the status line's
/// own 3s `GO!`: this one covers the screen while the player is waiting to
/// confirm the character screen, so it has to get out of the way.
const GO_DURATION: f32 = 1.6;
/// Entry of a freshly ticked glyph: shrinks into place as it fades in.
const TICK_IN: f32 = 0.28;
/// Exit of the glyph it replaces: swells outwards as it fades out.
const TICK_OUT: f32 = 0.28;
const TICK_IN_SCALE: f32 = 1.25;
const TICK_OUT_SCALE: f32 = 1.5;
/// Ticks that blast a shockwave. Every tick would wear the effect out, so
/// only the last few get one.
const SHOCKWAVE_FROM_DIGIT: u32 = 3;
const SHOCKWAVE_DURATION: f32 = 0.5;
const SHOCKWAVE_SPREAD: f32 = 0.6;
const GO_SHOCKWAVE_DURATION: f32 = 0.7;
const GO_SHOCKWAVE_SPREAD: f32 = 1.6;
/// Peak darkening at the screen edges, reached as the countdown hits zero.
const VIGNETTE_MAX: f32 = 0.3;
/// How fast the screen clears once the race is on.
const GO_CLEAR: f32 = 0.4;
const TITLE_ALPHA: f32 = 0.85;
const TITLE_FADE_IN: f32 = 0.4;

/// Share of the display's reference dimension each part takes.
const DIGIT_SIZE: f32 = 0.13;
const RING_RADIUS: f32 = 0.115;
const RING_THICKNESS: f32 = 0.009;
const TITLE_SIZE: f32 = 0.026;
/// Gap between the ring and the race name, in title font sizes.
const TITLE_GAP: f32 = 2.0;

fn ease_out_cubic(t: f32) -> f32 {
    let remaining = 1.0 - t.clamp(0.0, 1.0);
    1.0 - remaining * remaining * remaining
}

/// Build the frame for a countdown of `total` seconds, `elapsed` after the
/// race start message.
///
/// Returns `None` when there is nothing left to draw: before a countdown
/// exists (`total` zero), or once the `GO!` burst is over.
pub fn countdown_frame(total: Duration, elapsed: Duration) -> Option<CountdownFrame> {
    let total_s = total.as_secs_f32();
    let elapsed_s = elapsed.as_secs_f32();
    if total_s <= 0.0 || elapsed_s >= total_s + GO_DURATION {
        return None;
    }

    // Past zero: the race is on. The digit that was on screen leaves on the
    // same crossfade as any other tick, with GO! taking its slot.
    if elapsed_s >= total_s {
        let age = elapsed_s - total_s;
        let progress = (age / GO_DURATION).clamp(0.0, 1.0);
        // The web's GO! keyframes, on a shorter clock: a pop into place,
        // then a slow settle under a late fade.
        let (scale, alpha) = if progress < 0.15 {
            (1.4 - 0.4 * ease_out_cubic(progress / 0.15), 1.0)
        } else if progress < 0.7 {
            (1.0, 1.0)
        } else {
            let out = (progress - 0.7) / 0.3;
            (1.0 - 0.1 * out, 1.0 - out)
        };
        // GO! enters on the same crossfade as the digits, so it never stacks
        // opaque over the 1 still flying out from under it.
        let alpha = alpha * ease_out_cubic(age / TICK_IN);
        // Everything the countdown had put on screen lifts together, so the
        // race starts on a clean image well before the burst is over.
        let clearing = 1.0 - (age / GO_CLEAR).clamp(0.0, 1.0);
        return Some(CountdownFrame {
            incoming: Glyph {
                label: GlyphLabel::Go,
                scale,
                alpha,
            },
            outgoing: outgoing_glyph(GlyphLabel::Digit(1), age),
            ring_fill: 0.0,
            ring_alpha: clearing,
            shockwave: shockwave(age, GO_SHOCKWAVE_DURATION, GO_SHOCKWAVE_SPREAD, 0.85),
            vignette: VIGNETTE_MAX * clearing,
            title_alpha: TITLE_ALPHA * clearing,
        });
    }

    let remaining = total_s - elapsed_s;
    let current = remaining.ceil().max(1.0);
    let age = current - remaining;
    let entry = ease_out_cubic(age / TICK_IN);
    // The first digit has no predecessor to push out.
    let previous = (current + 1.0 <= total_s.ceil()).then(|| GlyphLabel::Digit(current as u32 + 1));
    let progress = elapsed_s / total_s;

    Some(CountdownFrame {
        incoming: Glyph {
            label: GlyphLabel::Digit(current as u32),
            scale: TICK_IN_SCALE - (TICK_IN_SCALE - 1.0) * entry,
            alpha: entry,
        },
        outgoing: previous.and_then(|label| outgoing_glyph(label, age)),
        ring_fill: remaining / total_s,
        ring_alpha: 1.0,
        shockwave: if current as u32 <= SHOCKWAVE_FROM_DIGIT {
            shockwave(age, SHOCKWAVE_DURATION, SHOCKWAVE_SPREAD, 0.7)
        } else {
            None
        },
        // Quadratic, so the screen barely moves early on and closes in over
        // the last few seconds.
        vignette: VIGNETTE_MAX * progress * progress,
        title_alpha: TITLE_ALPHA * (elapsed_s / TITLE_FADE_IN).clamp(0.0, 1.0),
    })
}

/// The glyph a tick pushed out, `age` seconds ago.
fn outgoing_glyph(label: GlyphLabel, age: f32) -> Option<Glyph> {
    let out = age / TICK_OUT;
    (out < 1.0).then(|| Glyph {
        label,
        scale: 1.0 + (TICK_OUT_SCALE - 1.0) * ease_out_cubic(out),
        alpha: 1.0 - out,
    })
}

/// The ring blast a tick fired `age` seconds ago, while it is still visible.
fn shockwave(age: f32, duration: f32, spread: f32, peak_alpha: f32) -> Option<Shockwave> {
    let progress = age / duration;
    (progress < 1.0).then(|| {
        let eased = ease_out_cubic(progress);
        Shockwave {
            radius_factor: 1.0 + spread * eased,
            thickness_factor: 1.0 - 0.75 * eased,
            alpha: peak_alpha * (1.0 - progress),
        }
    })
}

/// The arc of ring left to draw at `fill`, or `None` once it is empty.
///
/// The arc always ends at 12 o'clock and starts where the hand has got to:
/// what drains is its start, walking clockwise away from 12, the way a clock
/// hand erases the ring behind itself. Segments are spent in proportion to
/// what is left, so the facet size (and with it the smoothness) does not
/// change as the ring empties.
pub fn ring_arc(layout: &CountdownLayout, fill: f32) -> Option<RingArc> {
    if fill <= 0.0 {
        return None;
    }
    let fill = fill.min(1.0);
    let segments = ((layout.ring_segments as f32 * fill).ceil() as usize).max(1);
    Some(RingArc {
        // Screen space grows downwards, so -pi/2 is 12 o'clock and a growing
        // angle turns clockwise.
        start_angle: -std::f32::consts::FRAC_PI_2 + std::f32::consts::TAU * (1.0 - fill),
        step: std::f32::consts::TAU * fill / segments as f32,
        segments,
    })
}

/// Compute the countdown's geometry for a display of `display` pixels.
pub fn countdown_layout(display: [f32; 2]) -> CountdownLayout {
    // Height drives the composition, so an ultrawide gets the same countdown
    // as a 16:9 of the same height. The width only takes over on a window
    // narrow enough that a height-sized ring would run off its sides.
    let base = display[1].min(display[0] * 0.75);
    let ring_radius = base * RING_RADIUS;
    let title_font_px = (base * TITLE_SIZE).max(11.0);

    CountdownLayout {
        center: [display[0] * 0.5, display[1] * 0.5],
        digit_font_px: base * DIGIT_SIZE,
        title_font_px,
        title_y: display[1] * 0.5 - ring_radius - title_font_px * TITLE_GAP,
        ring_radius,
        ring_thickness: (base * RING_THICKNESS).max(2.0),
        // Segment count follows the radius so the arc stays smooth at 4K
        // without spending vertices on a 720p ring.
        ring_segments: ((ring_radius * 0.75) as usize).clamp(48, 192),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TOTAL: Duration = Duration::from_secs(10);

    fn at(elapsed_s: f32) -> CountdownFrame {
        countdown_frame(TOTAL, Duration::from_secs_f32(elapsed_s))
            .expect("countdown should still be drawing")
    }

    fn digit(frame: &CountdownFrame) -> Option<u32> {
        match frame.incoming.label {
            GlyphLabel::Digit(d) => Some(d),
            GlyphLabel::Go => None,
        }
    }

    #[test]
    fn test_no_frame_once_the_go_burst_is_over() {
        assert!(countdown_frame(TOTAL, Duration::from_secs(30)).is_none());
    }

    #[test]
    fn test_no_frame_without_a_countdown() {
        assert!(countdown_frame(Duration::ZERO, Duration::ZERO).is_none());
    }

    #[test]
    fn test_digits_count_down_to_one() {
        assert_eq!(digit(&at(0.0)), Some(10));
        assert_eq!(digit(&at(0.5)), Some(10));
        assert_eq!(digit(&at(1.0)), Some(9));
        assert_eq!(digit(&at(9.0)), Some(1));
        assert_eq!(digit(&at(9.99)), Some(1));
    }

    #[test]
    fn test_first_digit_has_nothing_to_crossfade_out() {
        assert_eq!(at(0.0).outgoing, None);
    }

    #[test]
    fn test_a_tick_crossfades_the_previous_digit_out() {
        let frame = at(1.02);
        let outgoing = frame.outgoing.expect("the 10 should still be leaving");
        assert_eq!(outgoing.label, GlyphLabel::Digit(10));
        assert!(outgoing.scale > frame.incoming.scale.min(1.0));
    }

    #[test]
    fn test_the_outgoing_digit_clears_before_the_next_tick() {
        assert_eq!(at(1.6).outgoing, None);
    }

    #[test]
    fn test_the_incoming_digit_settles_opaque_at_full_size() {
        let settled = at(1.9).incoming;
        assert!(
            (settled.scale - 1.0).abs() < 0.01,
            "scale {}",
            settled.scale
        );
        assert!(
            (settled.alpha - 1.0).abs() < 0.01,
            "alpha {}",
            settled.alpha
        );
    }

    #[test]
    fn test_go_takes_over_at_zero_and_the_last_digit_flies_out() {
        let frame = at(10.02);
        assert_eq!(frame.incoming.label, GlyphLabel::Go);
        assert_eq!(
            frame.outgoing.map(|g| g.label),
            Some(GlyphLabel::Digit(1)),
            "the 1 should leave like any other tick"
        );
    }

    #[test]
    fn test_the_ring_drains_over_the_countdown() {
        let samples: Vec<f32> = (0..=10).map(|i| at(i as f32 * 0.999).ring_fill).collect();
        assert!(
            (samples[0] - 1.0).abs() < 0.01,
            "starts full: {:?}",
            samples
        );
        for pair in samples.windows(2) {
            assert!(pair[1] < pair[0], "ring should only drain: {:?}", samples);
        }
        assert!(at(9.99).ring_fill < 0.01);
        assert_eq!(at(10.5).ring_fill, 0.0, "empty once the race is on");
    }

    #[test]
    fn test_shockwave_fires_only_on_the_last_three_ticks() {
        for elapsed in [0.02, 1.02, 5.02, 6.02] {
            assert!(
                at(elapsed).shockwave.is_none(),
                "no shockwave at {elapsed}s"
            );
        }
        for elapsed in [7.02, 8.02, 9.02] {
            assert!(at(elapsed).shockwave.is_some(), "shockwave at {elapsed}s");
        }
        assert!(at(10.02).shockwave.is_some(), "GO! blasts too");
    }

    #[test]
    fn test_a_shockwave_expands_as_it_fades() {
        let early = at(9.05).shockwave.expect("just fired");
        let late = at(9.4).shockwave.expect("still expanding");
        assert!(late.radius_factor > early.radius_factor);
        assert!(late.alpha < early.alpha);
        assert!(late.thickness_factor < early.thickness_factor);
    }

    #[test]
    fn test_a_shockwave_clears_before_the_next_tick() {
        assert!(at(9.9).shockwave.is_none());
    }

    #[test]
    fn test_the_vignette_builds_up_then_lifts_on_go() {
        let build: Vec<f32> = (0..=10).map(|i| at(i as f32 * 0.999).vignette).collect();
        for pair in build.windows(2) {
            assert!(pair[1] > pair[0], "vignette should only build: {build:?}");
        }
        assert!(
            at(10.6).vignette < build[10] * 0.2,
            "the screen clears right after GO!"
        );
    }

    #[test]
    fn test_go_crossfades_in_like_any_other_glyph() {
        assert!(at(10.01).incoming.alpha < 0.3, "GO! enters transparent");
        assert!(at(10.4).incoming.alpha > 0.99, "and lands opaque");
    }

    #[test]
    fn test_the_ring_lifts_off_screen_after_go() {
        assert_eq!(at(5.0).ring_alpha, 1.0, "solid while counting");
        assert!(at(10.2).ring_alpha < 1.0, "fading once the race is on");
        assert_eq!(at(10.6).ring_alpha, 0.0, "gone before the last frame");
    }

    #[test]
    fn test_the_race_name_fades_in_at_the_start() {
        assert!(at(0.0).title_alpha < at(0.5).title_alpha);
    }

    #[test]
    fn test_every_frame_stays_within_drawable_bounds() {
        let mut elapsed = 0.0;
        while let Some(frame) = countdown_frame(TOTAL, Duration::from_secs_f32(elapsed)) {
            let mut glyphs = vec![frame.incoming];
            glyphs.extend(frame.outgoing);
            for glyph in glyphs {
                assert!(
                    (0.0..=1.0).contains(&glyph.alpha),
                    "alpha {} at {elapsed}s",
                    glyph.alpha
                );
                assert!(
                    (0.5..=2.0).contains(&glyph.scale),
                    "scale {} at {elapsed}s",
                    glyph.scale
                );
            }
            assert!(
                (0.0..=1.0).contains(&frame.ring_fill),
                "ring_fill {} at {elapsed}s",
                frame.ring_fill
            );
            assert!(
                (0.0..=0.5).contains(&frame.vignette),
                "vignette {} at {elapsed}s",
                frame.vignette
            );
            assert!(
                (0.0..=1.0).contains(&frame.title_alpha),
                "title_alpha {} at {elapsed}s",
                frame.title_alpha
            );
            if let Some(wave) = frame.shockwave {
                assert!(wave.radius_factor >= 1.0, "wave shrank at {elapsed}s");
                assert!(
                    (0.0..=1.0).contains(&wave.alpha),
                    "wave alpha {} at {elapsed}s",
                    wave.alpha
                );
                assert!(
                    (0.0..=1.0).contains(&wave.thickness_factor),
                    "wave thickness {} at {elapsed}s",
                    wave.thickness_factor
                );
            }
            elapsed += 1.0 / 120.0;
            assert!(elapsed < 60.0, "countdown never ended");
        }
    }

    #[test]
    fn test_the_composition_scales_with_the_display_height() {
        let hd = countdown_layout([1920.0, 1080.0]);
        let uhd = countdown_layout([3840.0, 2160.0]);
        assert!((uhd.digit_font_px / hd.digit_font_px - 2.0).abs() < 0.01);
        assert!((uhd.ring_radius / hd.ring_radius - 2.0).abs() < 0.01);
        assert!((uhd.ring_thickness / hd.ring_thickness - 2.0).abs() < 0.01);
        assert_eq!(uhd.center, [1920.0, 1080.0]);
    }

    #[test]
    fn test_an_ultrawide_composes_off_its_height_not_its_width() {
        let wide = countdown_layout([3440.0, 1440.0]);
        let standard = countdown_layout([2560.0, 1440.0]);
        assert_eq!(wide.ring_radius, standard.ring_radius);
        assert_eq!(wide.digit_font_px, standard.digit_font_px);
        assert_eq!(wide.center[0], 1720.0);
    }

    #[test]
    fn test_a_narrow_window_keeps_the_ring_on_screen() {
        let narrow = countdown_layout([800.0, 1200.0]);
        assert!(
            narrow.ring_radius * 2.0 + narrow.ring_thickness < 800.0,
            "ring {} wider than the window",
            narrow.ring_radius * 2.0
        );
    }

    #[test]
    fn test_the_race_name_sits_clear_of_the_ring() {
        for display in [[1280.0, 720.0], [1920.0, 1080.0], [3840.0, 2160.0]] {
            let layout = countdown_layout(display);
            assert!(
                layout.title_y + layout.title_font_px < layout.center[1] - layout.ring_radius,
                "title overlaps the ring at {display:?}"
            );
            assert!(layout.title_y > 0.0, "title off-screen at {display:?}");
        }
    }

    #[test]
    fn test_the_ring_stays_smooth_at_every_resolution() {
        for display in [[1280.0, 720.0], [1920.0, 1080.0], [3840.0, 2160.0]] {
            let layout = countdown_layout(display);
            // Sagitta: how far a segment's flat chord falls from the true
            // circle. Under a pixel and the ring reads as a curve.
            let half_angle = std::f32::consts::PI / layout.ring_segments as f32;
            let sagitta = layout.ring_radius * (1.0 - half_angle.cos());
            assert!(sagitta < 1.0, "{sagitta}px of faceting at {display:?}");
        }
        assert!(
            countdown_layout([3840.0, 2160.0]).ring_segments
                > countdown_layout([1280.0, 720.0]).ring_segments
        );
    }

    #[test]
    fn test_the_ring_arc_always_ends_at_twelve_oclock() {
        let layout = countdown_layout([1920.0, 1080.0]);
        let noon = -std::f32::consts::FRAC_PI_2 + std::f32::consts::TAU;
        for fill in [1.0, 0.75, 0.5, 0.1, 0.01] {
            let arc = ring_arc(&layout, fill).expect("still on screen");
            let end = arc.start_angle + arc.step * arc.segments as f32;
            assert!((end - noon).abs() < 1e-4, "fill {fill} ends at {end}");
        }
    }

    #[test]
    fn test_the_ring_arc_start_walks_clockwise_as_it_drains() {
        let layout = countdown_layout([1920.0, 1080.0]);
        let full = ring_arc(&layout, 1.0).unwrap().start_angle;
        let half = ring_arc(&layout, 0.5).unwrap().start_angle;
        let sliver = ring_arc(&layout, 0.05).unwrap().start_angle;
        assert!(half > full, "the hand went backwards");
        assert!(sliver > half, "the hand went backwards");
    }

    #[test]
    fn test_no_ring_arc_once_it_is_empty() {
        assert!(ring_arc(&countdown_layout([1920.0, 1080.0]), 0.0).is_none());
    }

    #[test]
    fn test_the_ring_arc_never_coarsens_as_it_empties() {
        let layout = countdown_layout([1920.0, 1080.0]);
        let full = ring_arc(&layout, 1.0).unwrap();
        assert_eq!(full.segments, layout.ring_segments);
        for fill in [0.9, 0.5, 0.25, 0.03, 0.001] {
            let arc = ring_arc(&layout, fill).expect("still on screen");
            // Segments are spent in proportion to what is left, rounded up,
            // so a draining ring is drawn at the same facet size or finer,
            // never coarser.
            assert!(
                arc.step <= full.step,
                "fill {fill} draws {} rad facets against {}",
                arc.step,
                full.step
            );
            assert!(arc.segments <= full.segments, "fill {fill} overspends");
        }
    }
}
