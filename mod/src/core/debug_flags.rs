//! Game debug flags watched for cheat detection.
//!
//! Elden Ring keeps its debug-menu switches ("One shot", "No death",
//! infinite stamina, ...) in a static byte array, libeldenring's
//! `chr_dbg_flags`: one byte per switch, non-zero = on, never saved. The
//! practice tool and TarnishedTool toggle these bytes; the retail game never
//! does. The mod reads them during a race and reports the ones it saw (see
//! docs/CHEAT_DETECTION.md).

/// Bytes read from `chr_dbg_flags`: offsets 0x0 through 0x12.
pub const DEBUG_FLAGS_LEN: usize = 0x13;

/// One watched byte.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DebugFlag {
    /// Offset from libeldenring's `chr_dbg_flags`.
    pub offset: usize,
    /// Wire name sent in `status_update.debug_flags`.
    pub name: &'static str,
}

/// The watched bytes. A flag's bit in a mask is its index in this table.
/// Bytes not listed here (+0x0, +0x8, +0x11) are ignored. Keep the names in
/// sync with `DEBUG_FLAG_NAMES` in
/// `server/speedfog_racing/services/debug_flags.py` and the labels in
/// `web/src/lib/debugFlags.ts`.
pub const DEBUG_FLAGS: &[DebugFlag] = &[
    DebugFlag {
        offset: 0x1,
        name: "player_no_death",
    },
    DebugFlag {
        offset: 0x2,
        name: "torrent_no_death",
    },
    DebugFlag {
        offset: 0x3,
        name: "one_shot",
    },
    DebugFlag {
        offset: 0x4,
        name: "infinite_consumables",
    },
    DebugFlag {
        offset: 0x5,
        name: "infinite_stamina",
    },
    DebugFlag {
        offset: 0x6,
        name: "infinite_fp",
    },
    DebugFlag {
        offset: 0x7,
        name: "infinite_arrows",
    },
    DebugFlag {
        offset: 0x9,
        name: "hidden",
    },
    DebugFlag {
        offset: 0xA,
        name: "silent",
    },
    DebugFlag {
        offset: 0xB,
        name: "all_no_death",
    },
    DebugFlag {
        offset: 0xC,
        name: "all_no_damage",
    },
    DebugFlag {
        offset: 0xD,
        name: "all_no_hit",
    },
    DebugFlag {
        offset: 0xE,
        name: "all_no_attack",
    },
    DebugFlag {
        offset: 0xF,
        name: "all_no_move",
    },
    DebugFlag {
        offset: 0x10,
        name: "all_no_ai",
    },
    DebugFlag {
        offset: 0x12,
        name: "infinite_aow_fp",
    },
];

/// Mask of the watched flags that are on in `bytes` (bit i = `DEBUG_FLAGS[i]`).
/// The game tests each byte against zero, so any non-zero value is "on".
pub fn mask_from_bytes(bytes: &[u8; DEBUG_FLAGS_LEN]) -> u32 {
    DEBUG_FLAGS
        .iter()
        .enumerate()
        .filter(|(_, flag)| bytes[flag.offset] != 0)
        .fold(0, |mask, (i, _)| mask | (1 << i))
}

/// Wire names of the flags in `mask`, in table order.
pub fn names(mask: u32) -> Vec<String> {
    DEBUG_FLAGS
        .iter()
        .enumerate()
        .filter(|(i, _)| mask & (1 << i) != 0)
        .map(|(_, flag)| flag.name.to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    fn bit(name: &str) -> u32 {
        1 << DEBUG_FLAGS.iter().position(|f| f.name == name).unwrap()
    }

    #[test]
    fn table_is_well_formed() {
        assert!(DEBUG_FLAGS.len() <= 32, "a mask is a u32");
        let offsets: HashSet<_> = DEBUG_FLAGS.iter().map(|f| f.offset).collect();
        let names: HashSet<_> = DEBUG_FLAGS.iter().map(|f| f.name).collect();
        assert_eq!(offsets.len(), DEBUG_FLAGS.len(), "offsets are unique");
        assert_eq!(names.len(), DEBUG_FLAGS.len(), "names are unique");
        assert!(DEBUG_FLAGS.iter().all(|f| f.offset < DEBUG_FLAGS_LEN));
    }

    #[test]
    fn all_zero_bytes_give_an_empty_mask() {
        assert_eq!(mask_from_bytes(&[0; DEBUG_FLAGS_LEN]), 0);
    }

    #[test]
    fn any_non_zero_byte_counts() {
        let mut bytes = [0; DEBUG_FLAGS_LEN];
        bytes[0x3] = 0x02; // not bit 0: the game compares the byte to zero
        assert_eq!(mask_from_bytes(&bytes), bit("one_shot"));
    }

    #[test]
    fn unwatched_offsets_are_ignored() {
        let mut bytes = [0; DEBUG_FLAGS_LEN];
        bytes[0x0] = 1;
        bytes[0x8] = 1;
        bytes[0x11] = 1;
        assert_eq!(mask_from_bytes(&bytes), 0);
    }

    #[test]
    fn names_follow_table_order() {
        let mask = bit("all_no_damage") | bit("player_no_death");
        assert_eq!(names(mask), vec!["player_no_death", "all_no_damage"]);
    }
}
