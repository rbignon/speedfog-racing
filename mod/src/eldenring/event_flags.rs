//! EMEVD event flag reader for Elden Ring
//!
//! Reads event flags from the game's VirtualMemoryFlag manager. Event flags
//! are set by EMEVD scripts (e.g., when the player walks through a fog gate
//! or defeats a boss).
//!
//! The flag storage uses a red-black tree (MSVC std::map) indexed by category
//! (flag_id / divisor), with each category page storing a bitfield of flag states.
//!
//! Algorithm based on SoulMemory/SoulSplitter (C#):
//! https://github.com/FrankvdStam/SoulSplitter

use std::fmt;

use libeldenring::memedit::PointerChain;
use tracing::{debug, info, warn};

/// Diagnostic status of the event flag reader.
pub enum FlagReaderStatus {
    /// base_ptr.read() returned None — memory not readable
    NoPtrRead,
    /// Manager pointer is null (game not fully loaded?)
    ManagerNull,
    /// Reader is functional
    Ok { manager_addr: usize, divisor: u32 },
}

impl fmt::Display for FlagReaderStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FlagReaderStatus::NoPtrRead => write!(f, "NO BASE PTR"),
            FlagReaderStatus::ManagerNull => write!(f, "MGR NULL"),
            FlagReaderStatus::Ok {
                manager_addr,
                divisor,
            } => write!(f, "OK (mgr=0x{:x}, div={})", manager_addr, divisor),
        }
    }
}

/// Reads EMEVD event flags from Elden Ring's VirtualMemoryFlag manager.
///
/// The manager stores flags in a red-black tree of category pages. Each page
/// covers `divisor` flags (typically 1000). Flags are stored as individual
/// bits within the category page.
pub struct EventFlagReader {
    /// Pointer to the VirtualMemoryFlag manager
    base_ptr: PointerChain<usize>,
}

impl EventFlagReader {
    /// Create a new EventFlagReader from the csfd4_virtual_memory_flag base address.
    pub fn new(csfd4_virtual_memory_flag: usize) -> Self {
        info!(
            base_addr = format_args!("0x{:x}", csfd4_virtual_memory_flag),
            "[EVENT_FLAGS] EventFlagReader created"
        );
        // csfd4_virtual_memory_flag is the address storing the CSFd4VirtualMemoryFlag*
        // Single dereference gives us the manager struct pointer
        let base_ptr = PointerChain::<usize>::new(&[csfd4_virtual_memory_flag]);
        Self { base_ptr }
    }

    /// Diagnose the current state of the flag reader without the ambiguity of Option<bool>.
    pub fn diagnose(&self) -> FlagReaderStatus {
        let manager = match self.base_ptr.read() {
            Some(m) => m,
            None => return FlagReaderStatus::NoPtrRead,
        };
        if manager == 0 {
            return FlagReaderStatus::ManagerNull;
        }
        let divisor: u32 = PointerChain::<u32>::new(&[manager + 0x1c])
            .read()
            .unwrap_or(0);
        FlagReaderStatus::Ok {
            manager_addr: manager,
            divisor,
        }
    }

    /// Check if a specific event flag is set in game memory.
    ///
    /// Returns `None` if memory read fails (game loading, etc.)
    pub fn is_flag_set(&self, flag_id: u32) -> Option<bool> {
        let manager = self.base_ptr.read()?;
        if manager == 0 {
            return None;
        }

        // Read divisor at manager + 0x1c (typically 1000)
        let divisor: u32 = PointerChain::<u32>::new(&[manager + 0x1c]).read()?;
        if divisor == 0 {
            warn!("[EVENT_FLAGS] Divisor is 0");
            return None;
        }

        let category = flag_id / divisor;
        let remainder = flag_id % divisor;

        // Traverse red-black tree at manager + 0x38 to find category page
        let data_ptr = self.find_category_page(manager, category)?;

        // Read the specific bit from the category page
        let byte_offset = (remainder >> 3) as usize;
        let bit_index = 7 - (remainder & 7);

        let byte_val: u8 = PointerChain::<u8>::new(&[data_ptr + byte_offset]).read()?;
        Some((byte_val & (1 << bit_index)) != 0)
    }

    /// Traverse the red-black tree to find the data pointer for a given category.
    ///
    /// The tree is an MSVC std::map with the following node layout:
    /// - `+0x00`: left child pointer
    /// - `+0x08`: parent pointer (used as initial child from root)
    /// - `+0x10`: right child pointer
    /// - `+0x19`: sentinel/color byte (0 = non-sentinel, !0 = sentinel)
    /// - `+0x20`: category key (i32)
    /// - `+0x28`: address calculation mode (1=formula, 2=absent, >2=direct ptr)
    /// - `+0x30`: data pointer or multiplier (depends on mode)
    fn find_category_page(&self, manager: usize, category: u32) -> Option<usize> {
        // Root node at manager + 0x38
        let root: usize = PointerChain::<usize>::new(&[manager + 0x38]).read()?;
        if root == 0 {
            return None;
        }

        // Start traversal from root's +0x8 child (per SoulMemory reference)
        let mut node: usize = PointerChain::<usize>::new(&[root + 0x8]).read()?;
        // Track the best candidate (last node where we went left, i.e., category <= node_value)
        let mut candidate: usize = root;

        // Guard against infinite loops (max 64 iterations)
        for _ in 0..64 {
            if node == 0 {
                break;
            }

            // Check sentinel byte at node + 0x19
            let sentinel: u8 = PointerChain::<u8>::new(&[node + 0x19]).read()?;
            if sentinel != 0 {
                break;
            }

            let node_value: u32 = PointerChain::<u32>::new(&[node + 0x20]).read()?;

            if node_value < category {
                // Go right: node + 0x10
                node = PointerChain::<usize>::new(&[node + 0x10]).read()?;
            } else {
                // Go left (or match): node + 0x0, record candidate
                candidate = node;
                node = PointerChain::<usize>::new(&[node]).read()?;
            }
        }

        // Verify the candidate actually matches our category
        if candidate == root {
            debug!(category, "[EVENT_FLAGS] Category not found in tree");
            return None;
        }
        let candidate_value: u32 = PointerChain::<u32>::new(&[candidate + 0x20]).read()?;
        if category < candidate_value {
            debug!(
                category,
                candidate_value, "[EVENT_FLAGS] Category not found (nearest was higher)"
            );
            return None;
        }

        // Read address calculation mode at candidate + 0x28
        let addr_mode: i32 = PointerChain::<i32>::new(&[candidate + 0x28]).read()?;
        match addr_mode - 1 {
            0 => {
                // Mode 1: formula — (manager[0x20] * node[0x30]) + manager[0x28]
                let multiplier: i32 = PointerChain::<i32>::new(&[candidate + 0x30]).read()?;
                let factor: i32 = PointerChain::<i32>::new(&[manager + 0x20]).read()?;
                let base_addr: usize = PointerChain::<usize>::new(&[manager + 0x28]).read()?;
                let calculated =
                    base_addr.wrapping_add((factor as i64 * multiplier as i64) as usize);
                if calculated == 0 {
                    return None;
                }
                Some(calculated)
            }
            1 => {
                // Mode 2: flag doesn't exist
                None
            }
            _ => {
                // Mode > 2: direct pointer at node + 0x30
                let data_ptr: usize = PointerChain::<usize>::new(&[candidate + 0x30]).read()?;
                if data_ptr == 0 {
                    return None;
                }
                Some(data_ptr)
            }
        }
    }
}
