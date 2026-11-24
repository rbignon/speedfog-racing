//! A relay member's save token: the value the server draws when it
//! validates a member's save, which binds the member to that save's
//! character for the whole race. The mod keeps it in saved event flags of
//! the save, one bit per flag (bit `i` in flag `base + i`), writes it into a
//! save that holds none, and reads it back after every load: a save that
//! carries another value is not the member's. This module turns a value
//! into its flags and back and judges what a read found; the race machine
//! decides when a read and a write are made (`RaceMachine::tick`). Pure:
//! nothing here reads the game or logs.

use std::time::Duration;

/// Writes of the token into one save that did not read back, before the
/// mod gives up writing it there (until the next load or a new token).
pub const WRITE_ATTEMPTS: u32 = 3;
/// A read of the token flags that found one of them unreadable is asked
/// again no sooner than this: flags that never read cost one category
/// lookup per interval, not one per frame.
pub const UNREADABLE_RETRY: Duration = Duration::from_millis(500);

/// What a read of the token flags makes of the save loaded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    /// The server has drawn no token for the member yet: the save is not
    /// judged.
    NotExpected,
    /// The save carries the member's token, and the server knows it.
    Good,
    /// The save carries the member's token, and the server does not know it
    /// yet: the mod confirms it (`relay_bound`).
    Confirm,
    /// The save carries no token and the member is bound to none yet: the
    /// mod writes it.
    Write,
    /// The save carries another value, or none while the member is bound:
    /// it is not the member's save.
    Wrong,
}

/// The value the flags hold: bit `i` is the `i`-th item (items past the
/// 32nd are ignored).
pub fn value_of(bits: impl IntoIterator<Item = bool>) -> u32 {
    bits.into_iter()
        .take(u32::BITS as usize)
        .enumerate()
        .fold(0, |value, (i, set)| value | (u32::from(set) << i))
}

/// Every flag that holds `token` over `bits` flags from `base`, with the
/// value it must read, up or down (flags past the 32nd down).
pub fn writes(base: u32, bits: u32, token: u32) -> Vec<(u32, bool)> {
    (0..bits)
        .map(|i| {
            let set = i < u32::BITS && token >> i & 1 == 1;
            (base.wrapping_add(i), set)
        })
        .collect()
}

/// The verdict on a save whose token flags read `read`, for a member whose
/// token is `expected` (`None`: none drawn yet) and is `bound` or not.
pub fn judge(expected: Option<u32>, bound: bool, read: u32) -> Verdict {
    match expected {
        None => Verdict::NotExpected,
        Some(token) if read == token => {
            if bound {
                Verdict::Good
            } else {
                Verdict::Confirm
            }
        }
        Some(_) if read == 0 && !bound => Verdict::Write,
        Some(_) => Verdict::Wrong,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_token_survives_its_flags() {
        for token in [1u32, 2, 0x00AB_CDEF, (1 << 24) - 1] {
            let flags = writes(1_050_297_900, 24, token);
            assert_eq!(flags.len(), 24);
            assert_eq!(flags[0].0, 1_050_297_900);
            assert_eq!(value_of(flags.iter().map(|f| f.1)), token);
        }
    }

    #[test]
    fn the_verdicts() {
        assert_eq!(judge(None, false, 77), Verdict::NotExpected);
        assert_eq!(judge(Some(5), true, 5), Verdict::Good);
        assert_eq!(judge(Some(5), false, 5), Verdict::Confirm);
        assert_eq!(judge(Some(5), false, 0), Verdict::Write);
        assert_eq!(judge(Some(5), true, 0), Verdict::Wrong); // bound, and the save has no token
        assert_eq!(judge(Some(5), false, 6), Verdict::Wrong);
        assert_eq!(judge(Some(5), true, 6), Verdict::Wrong);
    }
}
