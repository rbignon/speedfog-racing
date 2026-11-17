//! What the shell writes to spawn the Hunter through the game's debug
//! character creator (`eldenring::hunter`): the creator's offset in
//! WorldChrMan for a game build, the model name, the point behind the
//! player he appears at, and how a look and his end judge a character of
//! his row from its HP. Pure: the shell reads and writes the game.
//!
//! The point follows the player's physics module (the Havok position the
//! creator takes, and the orientation quaternion next to it): the yaw is
//! `2 * atan2(q.y, q.w)` and the player faces `(sin yaw, 0, cos yaw)`, as
//! the practice tool's target widget reads an enemy's angle. The sign is
//! derived, not seen in game: the shell logs the placement.

use std::f32::consts::{PI, TAU};

/// The RTTI name of `CS::CSDebugChrCreator`, NUL included: the creator is
/// trusted only when its type descriptor holds exactly these bytes.
pub const CREATOR_RTTI_NAME: &[u8] = b".?AVCSDebugChrCreator@CS@@\0";

/// The creator's model name field, in UTF-16 code units, NUL padded.
pub const MODEL_NAME_LEN: usize = 0x20;

/// He appears this far behind the player, on the ground plane (metres)...
pub const BEHIND_M: f32 = 3.0;
/// ...and this far above the player's position, out of the ground on a
/// slope.
pub const LIFT_M: f32 = 0.5;

/// Under this length, `(q.y, q.w)` holds no yaw: not a character's
/// orientation (a zeroed read).
const MIN_YAW_NORM: f32 = 1e-3;

/// WorldChrMan's offset to its `CSDebugChrCreator` pointer on the game
/// build `exe_version` (eldenring.exe major, minor, patch). The field moved
/// between 1.17.1 and 1.17.2 (two fields added before it), so each build
/// gets its own and any other build none: the Hunter is off there.
pub fn creator_offset(exe_version: (u32, u32, u32)) -> Option<usize> {
    match exe_version {
        // 1.17.0 and 1.17.1
        (2, 7, 0) | (2, 7, 1) => Some(0x1E648),
        // 1.17.2
        (2, 7, 2) => Some(0x1E658),
        _ => None,
    }
}

/// The creator's model name for character `chr_id`: `c` and its four
/// digits, NUL padded (the game's model names, `c2130` for Margit). `None`
/// past four digits: no such model.
pub fn model_name(chr_id: u32) -> Option<[u16; MODEL_NAME_LEN]> {
    if chr_id > 9999 {
        return None;
    }
    let mut name = [0u16; MODEL_NAME_LEN];
    for (unit, code) in name.iter_mut().zip(format!("c{chr_id:04}").encode_utf16()) {
        *unit = code;
    }
    Some(name)
}

/// Where the Hunter appears.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Placement {
    /// The player's facing in radians, in (-pi, pi]: 0 faces +z, pi/2 +x.
    pub yaw: f32,
    /// `BEHIND_M` behind the player along that facing, `LIFT_M` up.
    pub spawn: [f32; 3],
}

/// The Hunter's spawn point from the player's physics `position` (x, y, z)
/// and orientation quaternion (x, y, z, w). `None` when a value is not
/// finite or the quaternion holds no yaw: misread memory, no spawn.
pub fn placement(position: [f32; 3], orientation: [f32; 4]) -> Option<Placement> {
    if !position.iter().chain(&orientation).all(|v| v.is_finite()) {
        return None;
    }
    let [_, qy, _, qw] = orientation;
    if qy.hypot(qw) < MIN_YAW_NORM {
        return None;
    }
    let mut yaw = 2.0 * qy.atan2(qw);
    if yaw > PI {
        yaw -= TAU;
    } else if yaw <= -PI {
        yaw += TAU;
    }
    let (sin, cos) = yaw.sin_cos();
    let [x, y, z] = position;
    Some(Placement {
        yaw,
        spawn: [x - BEHIND_M * sin, y + LIFT_M, z - BEHIND_M * cos],
    })
}

/// Whether a character of the Hunter's row is alive for his end and for a
/// request's check for one already there: its HP read (`None`: unreadable)
/// and above 0. The end writes 0 HP only over such a character, never over
/// one it could not read.
pub fn alive(hp: Option<i32>) -> bool {
    hp.is_some_and(|hp| hp > 0)
}

/// Whether a look finds the Hunter in a character of his row, HP `hp`
/// (`None`: unreadable); `seen`: the watched request's Hunter was seen
/// before. A read HP decides (above 0). An unreadable one is no sign he is
/// gone: one already seen keeps hunting, so his end still comes and kills
/// him; one never seen is not seen yet, and the next look tries again.
pub fn found_by_a_look(hp: Option<i32>, seen: bool) -> bool {
    hp.map_or(seen, |hp| hp > 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    const AT: [f32; 3] = [120.5, -14.0, 87.25];

    /// The quaternion of a rotation by `yaw` radians about the vertical.
    fn facing(yaw: f32) -> [f32; 4] {
        let (sin, cos) = (yaw / 2.0).sin_cos();
        [0.0, sin, 0.0, cos]
    }

    fn assert_near(a: [f32; 3], b: [f32; 3]) {
        let close = a.iter().zip(&b).all(|(x, y)| (x - y).abs() < 1e-3);
        assert!(close, "{a:?}, expected {b:?}");
    }

    #[test]
    fn only_the_1_17_builds_have_a_creator() {
        let shared = creator_offset((2, 7, 0));
        assert!(shared.is_some());
        assert_eq!(creator_offset((2, 7, 1)), shared);
        // 1.17.2 moved the field: the 1.17.0 offset is another object there.
        assert!(creator_offset((2, 7, 2)).is_some_and(|o| Some(o) != shared));
        for other in [(2, 6, 2), (2, 7, 3), (2, 8, 0), (1, 7, 0)] {
            assert_eq!(creator_offset(other), None, "{other:?}");
        }
    }

    #[test]
    fn the_model_name_is_c_and_four_digits() {
        let name = model_name(2130).unwrap();
        assert_eq!(String::from_utf16(&name[..5]).unwrap(), "c2130");
        assert!(name[5..].iter().all(|&unit| unit == 0), "{name:?}");
        let padded = model_name(100).unwrap();
        assert_eq!(String::from_utf16(&padded[..5]).unwrap(), "c0100");
        assert_eq!(padded[5], 0);
        assert_eq!(model_name(10000), None);
    }

    #[test]
    fn he_appears_behind_the_facing() {
        let [x, y, z] = AT;
        // Facing +z: behind is -z.
        let ahead_z = placement(AT, [0.0, 0.0, 0.0, 1.0]).unwrap();
        assert_near(ahead_z.spawn, [x, y + LIFT_M, z - BEHIND_M]);
        // Facing +x: behind is -x.
        assert_near(
            placement(AT, facing(PI / 2.0)).unwrap().spawn,
            [x - BEHIND_M, y + LIFT_M, z],
        );
        // Facing -z and -x.
        assert_near(
            placement(AT, facing(PI)).unwrap().spawn,
            [x, y + LIFT_M, z + BEHIND_M],
        );
        assert_near(
            placement(AT, facing(-PI / 2.0)).unwrap().spawn,
            [x + BEHIND_M, y + LIFT_M, z],
        );
    }

    #[test]
    fn three_metres_back_and_half_a_metre_up_whatever_the_facing() {
        for step in -12..=12 {
            let yaw = step as f32 * PI / 12.0;
            let placed = placement(AT, facing(yaw)).unwrap();
            let [dx, dy, dz] = [
                placed.spawn[0] - AT[0],
                placed.spawn[1] - AT[1],
                placed.spawn[2] - AT[2],
            ];
            assert!((dx.hypot(dz) - BEHIND_M).abs() < 1e-3, "{yaw}: {placed:?}");
            assert!((dy - LIFT_M).abs() < 1e-6, "{yaw}: {placed:?}");
            // The yaw read back, within (-pi, pi] (pi and -pi are one
            // facing: compared around the circle).
            assert!(placed.yaw > -PI && placed.yaw <= PI, "{yaw}: {placed:?}");
            let apart = (placed.yaw - yaw + PI).rem_euclid(TAU) - PI;
            assert!(apart.abs() < 1e-4, "{yaw}: {placed:?}");
        }
    }

    #[test]
    fn a_rotation_places_him_the_same_whatever_its_quaternion() {
        for yaw in [0.3, 1.9, -2.6, PI] {
            let q = facing(yaw);
            let expected = placement(AT, q).unwrap();
            // -q is the same rotation; a quaternion not normalized too.
            for other in [q.map(|v| -v), q.map(|v| v * 2.0), q.map(|v| v * 0.5)] {
                let placed = placement(AT, other).unwrap();
                assert_near(placed.spawn, expected.spawn);
            }
        }
    }

    #[test]
    fn misread_values_place_nothing() {
        assert_eq!(placement([f32::NAN, 0.0, 0.0], facing(0.0)), None);
        assert_eq!(placement(AT, [0.0, f32::INFINITY, 0.0, 1.0]), None);
        assert_eq!(placement(AT, [0.0; 4]), None);
    }

    #[test]
    fn an_unreadable_hp_keeps_a_seen_hunter_and_is_never_killed() {
        // A look: a misread HP is no sign he is gone once seen, so the hunt
        // goes on to its end; before that, he is not seen yet.
        assert!(found_by_a_look(None, true));
        assert!(!found_by_a_look(None, false));
        // A read HP decides, seen or not.
        for seen in [false, true] {
            assert!(found_by_a_look(Some(1), seen));
            assert!(!found_by_a_look(Some(0), seen));
            assert!(!found_by_a_look(Some(-5), seen));
        }
        // The end (and a request's check for one already there): only an HP
        // read above 0, so 0 HP is never written over an unreadable one.
        assert!(alive(Some(1)));
        assert!(!alive(Some(0)));
        assert!(!alive(None));
    }
}
