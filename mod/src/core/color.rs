//! Color utilities
//!
//! Functions for parsing and converting colors between hex strings and ImGui RGBA arrays.

/// Parse hex color "#RRGGBB" to [f32; 4] for ImGui
///
/// Returns RGBA as floats in the range [0.0, 1.0].
/// Falls back to white if the hex string is invalid.
pub fn parse_hex_color(hex: &str, alpha: f32) -> [f32; 4] {
    let hex = hex.trim_start_matches('#');
    if hex.len() < 6 {
        return [1.0, 1.0, 1.0, alpha];
    }
    let r = u8::from_str_radix(&hex[0..2], 16).unwrap_or(255);
    let g = u8::from_str_radix(&hex[2..4], 16).unwrap_or(255);
    let b = u8::from_str_radix(&hex[4..6], 16).unwrap_or(255);
    [r as f32 / 255.0, g as f32 / 255.0, b as f32 / 255.0, alpha]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_basic() {
        assert_eq!(parse_hex_color("#FF0000", 1.0), [1.0, 0.0, 0.0, 1.0]);
        assert_eq!(parse_hex_color("#00FF00", 1.0), [0.0, 1.0, 0.0, 1.0]);
        assert_eq!(parse_hex_color("#0000FF", 1.0), [0.0, 0.0, 1.0, 1.0]);
    }

    #[test]
    fn test_parse_alpha() {
        assert_eq!(parse_hex_color("#FF0000", 0.5), [1.0, 0.0, 0.0, 0.5]);
        assert_eq!(parse_hex_color("#FF0000", 0.0), [1.0, 0.0, 0.0, 0.0]);
    }

    #[test]
    fn test_parse_without_hash() {
        assert_eq!(parse_hex_color("FF0000", 1.0), [1.0, 0.0, 0.0, 1.0]);
    }

    #[test]
    fn test_parse_invalid_fallback() {
        assert_eq!(parse_hex_color("#FFF", 1.0), [1.0, 1.0, 1.0, 1.0]);
        assert_eq!(parse_hex_color("", 1.0), [1.0, 1.0, 1.0, 1.0]);
    }

    #[test]
    fn charter_hex_values_all_parse() {
        // Sentinel: every hex token cited in docs/GRAPHIC_CHARTER.md must
        // parse successfully (i.e. not hit the white fallback). This catches
        // typos in the CachedColors constructor; the markdown charter remains
        // the source of truth.
        let tokens = [
            ("#C8A44E", "gold"),
            ("#4AAE8C", "success"),
            ("#DC6A51", "danger"),
            ("#B5462F", "danger_dark"),
            ("#A99BC9", "purple"),
            ("#0F1923", "background"),
            ("#E8E6E1", "text"),
            ("#96A0AD", "text_disabled"),
            ("#253550", "border"),
        ];
        let white_fallback = [1.0, 1.0, 1.0, 1.0];
        for (hex, name) in tokens {
            let rgba = parse_hex_color(hex, 1.0);
            assert_ne!(rgba, white_fallback, "{name} ({hex}) hit white fallback");
        }
    }
}
