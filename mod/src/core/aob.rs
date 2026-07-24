//! Platform-independent array-of-bytes (AOB) pattern matching over a byte
//! slice. `Some(b)` matches that byte exactly; `None` is a wildcard. The
//! Windows-specific module scanning and patching that builds on this lives in
//! `eldenring::scan`.

/// One byte of an AOB pattern: `Some(b)` matches exactly, `None` is a wildcard.
pub type PatternByte = Option<u8>;

/// True if `pattern` matches `haystack` starting at `offset`.
/// Caller guarantees `offset + pattern.len() <= haystack.len()`.
fn matches_at(haystack: &[u8], offset: usize, pattern: &[PatternByte]) -> bool {
    pattern
        .iter()
        .enumerate()
        .all(|(j, p)| p.map_or(true, |b| haystack[offset + j] == b))
}

/// Index of the first place `pattern` matches in `haystack`, or `None`.
/// An empty pattern never matches.
pub fn find_first(haystack: &[u8], pattern: &[PatternByte]) -> Option<usize> {
    if pattern.is_empty() || haystack.len() < pattern.len() {
        return None;
    }
    let last = haystack.len() - pattern.len();
    (0..=last).find(|&i| matches_at(haystack, i, pattern))
}

/// Target address of a RIP-relative operand: the displacement is relative to
/// the address of the NEXT instruction (`instruction_addr + instruction_len`).
pub fn rip_relative_target(instruction_addr: usize, disp32: i32, instruction_len: usize) -> usize {
    instruction_addr
        .wrapping_add(instruction_len)
        .wrapping_add(disp32 as isize as usize)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn find_first_matches_with_wildcard() {
        let buf = [0x00, 0x00, 0x12, 0x34, 0x56, 0x78, 0x00];
        let pat = [Some(0x12), None, Some(0x56), Some(0x78)];
        assert_eq!(find_first(&buf, &pat), Some(2));
    }

    #[test]
    fn find_first_none_when_absent() {
        assert_eq!(find_first(&[0u8; 8], &[Some(0xAA), Some(0xBB)]), None);
    }

    #[test]
    fn find_first_none_for_empty_pattern() {
        assert_eq!(find_first(&[0u8; 4], &[]), None);
    }

    #[test]
    fn rip_relative_target_resolves_forward_and_backward() {
        // cmp qword ptr [rip+disp32], 0 is 8 bytes; target = end of
        // instruction + displacement.
        assert_eq!(rip_relative_target(0x1000, 0xD0, 8), 0x10D8);
        assert_eq!(rip_relative_target(0x1000, -0x10, 8), 0xFF8);
    }
}
