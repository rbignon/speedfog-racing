//! Memory race item effects, on the play clock.
//!
//! Vanish, Unseen Foes, Slow-mo, Giant, the Camera and the Lightning's shrink
//! have no SpEffect row: the shell writes them into the game's memory. The race machine keeps
//! when each ends on the play clock (`core::play_clock`) and derives from the
//! live ones the state the game should hold (`MemoryState`), which the shell
//! writes. Pure timing: every method takes the play time.

use std::mem::discriminant;
use std::time::Duration;

use super::protocol::CameraVariant;

/// A memory effect with its value. The Giant and the Lightning's shrink are
/// both `Scale`: they write the same field.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum MemoryEffect {
    Vanish,
    UnseenFoes,
    SlowMo { speed: f32 },
    Scale { scale: f32 },
    Camera(CameraVariant),
}

/// What the game's memory holds for the memory effects. `Default` is the
/// game's own: the player and the foes shown, animation speed and scale 1,
/// the vanilla camera; the shell writes a `None` or `false` field as that
/// default.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct MemoryState {
    /// The player is not drawn: a Vanish, or a first-person Camera (the
    /// camera sits inside the body).
    pub player_hidden: bool,
    /// The enemies around the player are not drawn (Unseen Foes).
    pub foes_hidden: bool,
    /// The player's animation speed (Slow-mo).
    pub anim_speed: Option<f32>,
    /// The player's scale (Giant, the Lightning's shrink).
    pub scale: Option<f32>,
    pub camera: Option<CameraVariant>,
}

/// The LockCamParam fields the Camera writes, on one row (its values from
/// the in-memory param, 0x80-byte rows: `camDistTarget` at +0x00,
/// `chrOrgOffset_Y` at +0x0C, `camFovY` at +0x14).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CameraRow {
    /// Camera distance target [m].
    pub dist: f32,
    /// Height of the camera pivot over the character [m].
    pub height: f32,
    /// Vertical field of view [deg].
    pub fov_y: f32,
}

/// First person: the camera pivot at eye height, 0.1 m behind it (the
/// player hidden, `MemoryState::player_hidden`, or the body fills the view).
const FIRST_PERSON_DIST: f32 = 0.1;
const FIRST_PERSON_HEIGHT: f32 = 1.5;
/// Upside down: a vertical field of view past 180 deg flips the image.
const INVERTED_FOV_Y: f32 = 300.0;
const WIDE_FOV_Y: f32 = 120.0;

impl CameraRow {
    /// The row `self` (its vanilla values) under `variant`: the fields the
    /// variant sets take its values, the others keep the row's own, so
    /// one variant after another never stacks.
    pub fn with_variant(self, variant: CameraVariant) -> Self {
        match variant {
            CameraVariant::FirstPerson => Self {
                dist: FIRST_PERSON_DIST,
                height: FIRST_PERSON_HEIGHT,
                ..self
            },
            CameraVariant::Inverted => Self {
                fov_y: INVERTED_FOV_Y,
                ..self
            },
            CameraVariant::Wide => Self {
                fov_y: WIDE_FOV_Y,
                ..self
            },
            CameraVariant::Unknown => self,
        }
    }
}

#[derive(Debug, Default)]
pub struct MemoryEffects {
    /// Effect and its end on the play clock, one entry per kind, in the
    /// order they started.
    running: Vec<(MemoryEffect, Duration)>,
}

impl MemoryEffects {
    /// Run `effect` for `duration` from `play`. A kind already running keeps
    /// the later end and takes the new value: the latest hit shows.
    pub fn start(&mut self, effect: MemoryEffect, duration: Duration, play: Duration) {
        let ends_at = play + duration;
        let kind = discriminant(&effect);
        match self
            .running
            .iter_mut()
            .find(|(running, _)| discriminant(running) == kind)
        {
            Some((running, end)) => {
                *running = effect;
                *end = (*end).max(ends_at);
            }
            None => self.running.push((effect, ends_at)),
        }
    }

    /// The state the live effects give at `play`; an ended one leaves its
    /// field at the default unless another live effect sets it.
    pub fn state(&self, play: Duration) -> MemoryState {
        let mut state = MemoryState::default();
        for &(effect, end) in &self.running {
            if end <= play {
                continue;
            }
            match effect {
                MemoryEffect::Vanish => state.player_hidden = true,
                MemoryEffect::UnseenFoes => state.foes_hidden = true,
                MemoryEffect::SlowMo { speed } => state.anim_speed = Some(speed),
                MemoryEffect::Scale { scale } => state.scale = Some(scale),
                MemoryEffect::Camera(variant) => {
                    state.player_hidden |= variant == CameraVariant::FirstPerson;
                    state.camera = Some(variant);
                }
            }
        }
        state
    }

    /// Whether any effect has time left at `play`.
    pub fn any_live(&self, play: Duration) -> bool {
        self.running.iter().any(|&(_, end)| end > play)
    }

    /// Forget every effect (all ended, the run is over, or another one
    /// starts).
    pub fn clear(&mut self) {
        self.running.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(s: u64) -> Duration {
        Duration::from_secs(s)
    }

    #[test]
    fn a_shared_field_waits_for_the_last_effect() {
        // Vanish 15 s, a first-person Camera from 5 s to 20 s: both hide the
        // player, who shows again only when the Camera ends.
        let mut fx = MemoryEffects::default();
        fx.start(MemoryEffect::Vanish, secs(15), Duration::ZERO);
        let vanish = MemoryState {
            player_hidden: true,
            ..MemoryState::default()
        };
        assert_eq!(fx.state(secs(2)), vanish);
        fx.start(
            MemoryEffect::Camera(CameraVariant::FirstPerson),
            secs(15),
            secs(5),
        );
        let first_person = MemoryState {
            player_hidden: true,
            camera: Some(CameraVariant::FirstPerson),
            ..MemoryState::default()
        };
        for at in [5, 14, 15, 19] {
            assert_eq!(fx.state(secs(at)), first_person, "at {at} s");
        }
        assert_eq!(fx.state(secs(20)), MemoryState::default());
        assert!(fx.any_live(secs(19)));
        assert!(!fx.any_live(secs(20)));

        // A wide Camera instead: the player shows again at the Vanish's end.
        let mut fx = MemoryEffects::default();
        fx.start(MemoryEffect::Vanish, secs(15), Duration::ZERO);
        fx.start(MemoryEffect::Camera(CameraVariant::Wide), secs(15), secs(5));
        assert_eq!(
            fx.state(secs(14)),
            MemoryState {
                player_hidden: true,
                camera: Some(CameraVariant::Wide),
                ..MemoryState::default()
            }
        );
        assert_eq!(
            fx.state(secs(15)),
            MemoryState {
                camera: Some(CameraVariant::Wide),
                ..MemoryState::default()
            }
        );
        assert_eq!(fx.state(secs(20)), MemoryState::default());
    }

    #[test]
    fn a_camera_variant_sets_only_its_own_fields() {
        // Rows 0 and 1011 of the vanilla 1.17.0 regulation.
        for row in [
            CameraRow {
                dist: 3.8,
                height: 1.45,
                fov_y: 48.0,
            },
            CameraRow {
                dist: 10.0,
                height: 1.87,
                fov_y: 54.5,
            },
        ] {
            let first_person = row.with_variant(CameraVariant::FirstPerson);
            assert_ne!(first_person, row);
            assert_eq!(first_person.fov_y, row.fov_y);
            for variant in [CameraVariant::Inverted, CameraVariant::Wide] {
                let view = row.with_variant(variant);
                assert_ne!(view, row, "{variant:?}");
                assert_eq!((view.dist, view.height), (row.dist, row.height));
            }
            assert_ne!(
                row.with_variant(CameraVariant::Inverted),
                row.with_variant(CameraVariant::Wide)
            );
            assert_eq!(row.with_variant(CameraVariant::Unknown), row);
        }
    }

    #[test]
    fn a_second_hit_of_a_kind_takes_the_later_end() {
        // A shrink at 0, a Giant at 5: one scale, the Giant's, until 20 s.
        let mut fx = MemoryEffects::default();
        fx.start(MemoryEffect::Scale { scale: 0.5 }, secs(15), Duration::ZERO);
        assert_eq!(fx.state(secs(2)).scale, Some(0.5));
        fx.start(MemoryEffect::Scale { scale: 1.5 }, secs(15), secs(5));
        for at in [5, 15, 19] {
            assert_eq!(fx.state(secs(at)).scale, Some(1.5), "at {at} s");
        }
        assert_eq!(fx.state(secs(20)).scale, None);

        // A second Camera: the new variant, the later end, even from a
        // shorter hit.
        let mut fx = MemoryEffects::default();
        fx.start(
            MemoryEffect::Camera(CameraVariant::Inverted),
            secs(15),
            Duration::ZERO,
        );
        fx.start(MemoryEffect::Camera(CameraVariant::Wide), secs(15), secs(5));
        assert_eq!(fx.state(secs(19)).camera, Some(CameraVariant::Wide));
        fx.start(
            MemoryEffect::Camera(CameraVariant::FirstPerson),
            secs(1),
            secs(10),
        );
        let late = fx.state(secs(19));
        assert_eq!(late.camera, Some(CameraVariant::FirstPerson));
        assert!(late.player_hidden);
        assert_eq!(fx.state(secs(20)), MemoryState::default());
    }
}
