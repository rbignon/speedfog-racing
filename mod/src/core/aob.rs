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

/// Index of the match iff `pattern` occurs **exactly once** in `haystack`.
/// `Err(0)` = no match (including an empty pattern); `Err(2)` = two or more
/// matches (ambiguous). The caller uses this to refuse to patch when the
/// target is missing or not unique.
pub fn find_unique(haystack: &[u8], pattern: &[PatternByte]) -> Result<usize, usize> {
    if pattern.is_empty() || haystack.len() < pattern.len() {
        return Err(0);
    }
    let last = haystack.len() - pattern.len();
    let mut found: Option<usize> = None;
    for i in 0..=last {
        if matches_at(haystack, i, pattern) {
            if found.is_some() {
                return Err(2); // two or more matches: ambiguous
            }
            found = Some(i);
        }
    }
    found.ok_or(0)
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
    fn find_unique_returns_single_match() {
        let buf = [0x90, 0x12, 0x34, 0x90];
        assert_eq!(find_unique(&buf, &[Some(0x12), Some(0x34)]), Ok(1));
    }

    #[test]
    fn find_unique_errs_zero_when_absent() {
        assert_eq!(find_unique(&[0u8; 8], &[Some(0xAA)]), Err(0));
    }

    #[test]
    fn find_unique_errs_two_when_ambiguous() {
        let buf = [0xAB, 0x00, 0xAB, 0x00];
        assert_eq!(find_unique(&buf, &[Some(0xAB)]), Err(2));
    }

    #[test]
    fn find_unique_respects_wildcards() {
        let buf = [0x12, 0xFF, 0x34, 0x12, 0x00, 0x99];
        assert_eq!(find_unique(&buf, &[Some(0x12), None, Some(0x34)]), Ok(0));
    }
}
