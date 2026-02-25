//! Formatting utilities for race data display.

/// Format a gap in milliseconds as `+M:SS` or `+H:MM:SS`.
pub fn format_gap(ms: i32) -> String {
    let ms = ms.max(0) as u32;
    let secs = ms / 1000;
    let mins = secs / 60;
    let hours = mins / 60;
    if hours > 0 {
        format!("+{}:{:02}:{:02}", hours, mins % 60, secs % 60)
    } else {
        format!("+{}:{:02}", mins, secs % 60)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_gap_seconds() {
        assert_eq!(format_gap(5000), "+0:05");
    }

    #[test]
    fn test_format_gap_minutes() {
        assert_eq!(format_gap(135000), "+2:15");
    }

    #[test]
    fn test_format_gap_hours() {
        assert_eq!(format_gap(3_723_000), "+1:02:03");
    }

    #[test]
    fn test_format_gap_zero() {
        assert_eq!(format_gap(0), "+0:00");
    }

    #[test]
    fn test_format_gap_negative() {
        // Edge case: negative gap (shouldn't normally happen)
        assert_eq!(format_gap(-5000), "+0:00");
    }
}
