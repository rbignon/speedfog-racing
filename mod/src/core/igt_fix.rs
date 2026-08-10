//! IGT truncation-fix accumulator, ported from SoulSplitter's soulmods
//! (https://github.com/FrankvdStam/SoulSplitter, GPLv3; compatible with this
//! crate's AGPL-3.0).
//!
//! Elden Ring increments its in-game timer by `frame_delta * 1000 * 0.96`
//! (IGT deliberately runs at 96% of real time) and then truncates to whole
//! milliseconds. At a locked 60 FPS the product is exactly 16.0 and nothing
//! is lost; at any other framerate the discarded fraction accumulates, so a
//! machine that cannot hold 60 FPS runs a slower timer, an advantage in
//! IGT-ranked races. This accumulator carries the fraction across frames and
//! re-injects one whole millisecond whenever it exceeds 1.0, making the
//! corrected increments framerate-independent while keeping the official
//! 0.96 scale. The unsafe hook that feeds it lives in
//! `eldenring::igt_hook` (Windows-only).

/// Elden Ring's official IGT scale: the timer runs at 96% of real time.
pub const IGT_SCALE: f32 = 0.96;

pub struct IgtFix {
    /// Fractional milliseconds not yet credited to the timer.
    buffer: f32,
}

impl IgtFix {
    /// `const` so the hook can own one in a `static Mutex`.
    pub const fn new() -> Self {
        Self { buffer: 0.0 }
    }

    /// One frame's corrected IGT increment. `frame_delta_secs` is the raw
    /// frame delta in seconds (the game's xmm0 value at the hook site);
    /// the return value is the whole-millisecond delta to hand back to the
    /// game, whose own truncating cast then loses nothing.
    pub fn corrected_delta_ms(&mut self, frame_delta_secs: f32) -> f32 {
        let scaled = frame_delta_secs * 1000.0 * IGT_SCALE;
        // The game casts (truncates); floor explicitly like upstream and
        // bank the remainder.
        let mut floored = scaled.floor();
        self.buffer += scaled - floored;
        if self.buffer > 1.0 {
            self.buffer -= 1.0;
            floored += 1.0;
        }
        floored
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn locked_60fps_gains_nothing() {
        // 16.6667 * 0.96 = 16.0 exactly: the correction must not invent
        // extra milliseconds at the framerate the game is tuned for.
        let mut fix = IgtFix::new();
        let mut total = 0.0f64;
        for _ in 0..600 {
            total += fix.corrected_delta_ms(1.0 / 60.0) as f64;
        }
        assert_eq!(total, 9_600.0); // 10s of frames, scaled by 0.96
    }

    #[test]
    fn any_framerate_mix_stays_within_one_ms_of_scaled_real_time() {
        // The whole point of the port: corrected IGT tracks 0.96 x real
        // time regardless of framerate, where vanilla truncation drifts by
        // seconds per hour off 60 FPS.
        let fps_mix = [60.0f32, 58.0, 45.0, 30.0, 120.0, 59.94];
        let mut fix = IgtFix::new();
        let mut real_ms = 0.0f64;
        let mut igt_ms = 0.0f64;
        for i in 0..10_000 {
            let delta = 1.0 / fps_mix[i % fps_mix.len()];
            real_ms += (delta as f64) * 1000.0;
            igt_ms += fix.corrected_delta_ms(delta) as f64;
        }
        // Bound: at most the 1ms the buffer may still hold, plus f32
        // rounding dust across 10k frames.
        assert!(
            (igt_ms - real_ms * IGT_SCALE as f64).abs() <= 1.1,
            "drift {} ms",
            igt_ms - real_ms * IGT_SCALE as f64
        );
    }

    #[test]
    fn buffer_stays_bounded() {
        // Upstream carries on strictly-above-1.0, so after any call the
        // buffer sits in [0, 1.0]. A leak here would eventually inject
        // spurious milliseconds in bursts.
        let mut fix = IgtFix::new();
        for i in 0..1_000 {
            fix.corrected_delta_ms(1.0 / (30.0 + (i % 90) as f32));
            assert!(
                fix.buffer >= 0.0 && fix.buffer <= 1.0,
                "buffer {}",
                fix.buffer
            );
        }
    }

    #[test]
    fn corrected_delta_is_whole_and_never_negative() {
        let mut fix = IgtFix::new();
        for i in 0..1_000 {
            let d = fix.corrected_delta_ms(1.0 / (25.0 + (i % 100) as f32));
            assert!(d >= 0.0);
            assert_eq!(d, d.floor());
        }
    }
}
