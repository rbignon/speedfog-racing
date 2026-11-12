//! Race item feed: queued banners, timed reminder rows and the ink timer.
//!
//! Pure timing: every method takes `now`, nothing reads the clock.

use std::collections::VecDeque;
use std::time::{Duration, Instant};

use super::protocol::ItemBanner;

/// Colour family of a feed entry (danger for an effect received, gold otherwise).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FeedTone {
    Malus,
    Gain,
}

/// A banner ready to draw: every string is final (title already uppercase).
#[derive(Debug, Clone, PartialEq)]
pub struct FeedBanner {
    pub icon: String,
    pub title: String,
    pub line: String,
    pub detail: String,
    pub tone: FeedTone,
}

impl FeedBanner {
    /// Build from the wire banner, uppercasing the title once.
    pub fn from_wire(banner: &ItemBanner, tone: FeedTone) -> Self {
        Self {
            icon: banner.icon.clone(),
            title: banner.title.to_uppercase(),
            line: banner.line.clone(),
            detail: banner.detail.clone(),
            tone,
        }
    }
}

/// A timed row of the race panel.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedReminder {
    pub icon: String,
    pub text: String,
    pub tone: FeedTone,
    pub ends_at: Instant,
}

#[derive(Debug, Default)]
pub struct ItemFeed {
    /// Banner on screen and when it started; `None` implies an empty queue.
    current: Option<(FeedBanner, Instant)>,
    queue: VecDeque<FeedBanner>,
    reminders: Vec<FeedReminder>,
    ink_until: Option<Instant>,
}

impl ItemFeed {
    pub const BANNER_DURATION: Duration = Duration::from_secs(5);

    pub fn new() -> Self {
        Self::default()
    }

    /// Show the banner now when idle, else queue it behind the others.
    pub fn push_banner(&mut self, banner: FeedBanner, now: Instant) {
        if self.current.is_none() {
            self.current = Some((banner, now));
        } else {
            self.queue.push_back(banner);
        }
    }

    /// Drop the expired banner and start the next one at `now`; prune old reminders.
    pub fn advance(&mut self, now: Instant) {
        if let Some((_, started)) = &self.current {
            if now.saturating_duration_since(*started) >= Self::BANNER_DURATION {
                self.current = self.queue.pop_front().map(|b| (b, now));
            }
        }
        self.reminders.retain(|r| r.ends_at > now);
    }

    /// Banner on screen, if any (as of the last `advance`).
    pub fn banner(&self) -> Option<&FeedBanner> {
        self.current.as_ref().map(|(b, _)| b)
    }

    /// Add a reminder row; a second one with the same text keeps the latest end.
    pub fn add_reminder(
        &mut self,
        icon: String,
        text: String,
        tone: FeedTone,
        duration: Duration,
        now: Instant,
    ) {
        let ends_at = now + duration;
        if let Some(existing) = self.reminders.iter_mut().find(|r| r.text == text) {
            if ends_at > existing.ends_at {
                existing.ends_at = ends_at;
                existing.icon = icon;
                existing.tone = tone;
            }
        } else {
            self.reminders.push(FeedReminder {
                icon,
                text,
                tone,
                ends_at,
            });
        }
    }

    /// Live reminders with their time left; expired ones are skipped.
    pub fn reminders(&self, now: Instant) -> impl Iterator<Item = (&FeedReminder, Duration)> {
        self.reminders.iter().filter_map(move |r| {
            r.ends_at
                .checked_duration_since(now)
                .filter(|left| !left.is_zero())
                .map(|left| (r, left))
        })
    }

    /// Start or extend the ink; the latest end wins.
    pub fn set_ink(&mut self, duration: Duration, now: Instant) {
        let ends_at = now + duration;
        if self.ink_until.is_none_or(|current| ends_at > current) {
            self.ink_until = Some(ends_at);
        }
    }

    pub fn ink_active(&self, now: Instant) -> bool {
        self.ink_until.is_some_and(|end| now < end)
    }

    /// Drop the reminder rows and the ink; banners play on.
    pub fn clear_timers(&mut self) {
        self.reminders.clear();
        self.ink_until = None;
    }

    /// Forget everything (race change, disconnect).
    pub fn clear(&mut self) {
        *self = Self::default();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn banner(title: &str) -> FeedBanner {
        FeedBanner::from_wire(
            &ItemBanner {
                icon: "icon".into(),
                title: title.into(),
                line: "line".into(),
                detail: "detail".into(),
            },
            FeedTone::Malus,
        )
    }

    fn secs(s: u64) -> Duration {
        Duration::from_secs(s)
    }

    #[test]
    fn banners_queue_five_seconds_each() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        for t in ["a", "b", "c"] {
            feed.push_banner(banner(t), t0);
        }
        for (offset, expected) in [(0, "A"), (4, "A"), (5, "B"), (9, "B"), (10, "C")] {
            feed.advance(t0 + secs(offset));
            assert_eq!(feed.banner().unwrap().title, expected, "at +{offset}s");
        }
        feed.advance(t0 + secs(15));
        assert!(feed.banner().is_none());
    }

    #[test]
    fn a_banner_pushed_while_idle_starts_now() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        feed.push_banner(banner("a"), t0);
        feed.advance(t0 + secs(6));
        assert!(feed.banner().is_none());
        feed.push_banner(banner("b"), t0 + secs(20));
        feed.advance(t0 + secs(24));
        assert_eq!(feed.banner().unwrap().title, "B");
        feed.advance(t0 + secs(25));
        assert!(feed.banner().is_none());
    }

    #[test]
    fn reminder_with_the_same_text_keeps_the_latest_end() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        feed.add_reminder("i".into(), "Fat-roll".into(), FeedTone::Malus, secs(15), t0);
        feed.add_reminder(
            "i".into(),
            "Fat-roll".into(),
            FeedTone::Malus,
            secs(15),
            t0 + secs(5),
        );
        // A shorter later copy must not shorten the row.
        feed.add_reminder(
            "i".into(),
            "Fat-roll".into(),
            FeedTone::Malus,
            secs(1),
            t0 + secs(6),
        );
        let rows: Vec<_> = feed.reminders(t0 + secs(10)).collect();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].0.ends_at, t0 + secs(20));
        assert_eq!(rows[0].1, secs(10));
    }

    #[test]
    fn expired_reminders_disappear() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        feed.add_reminder("i".into(), "a".into(), FeedTone::Gain, secs(5), t0);
        feed.add_reminder("i".into(), "b".into(), FeedTone::Gain, secs(15), t0);
        let texts = |feed: &ItemFeed, at| {
            feed.reminders(at)
                .map(|(r, _)| r.text.clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(texts(&feed, t0 + secs(4)), ["a", "b"]);
        assert_eq!(texts(&feed, t0 + secs(5)), ["b"]);
        feed.advance(t0 + secs(20));
        assert!(feed.reminders.is_empty());
    }

    #[test]
    fn ink_keeps_the_latest_end() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        assert!(!feed.ink_active(t0));
        feed.set_ink(secs(15), t0);
        feed.set_ink(secs(15), t0 + secs(10));
        feed.set_ink(secs(1), t0 + secs(11));
        assert!(feed.ink_active(t0 + secs(24)));
        assert!(!feed.ink_active(t0 + secs(25)));
        feed.clear();
        assert!(!feed.ink_active(t0 + secs(12)));
    }

    #[test]
    fn title_is_uppercased_on_receipt() {
        assert_eq!(banner("Red Shell").title, "RED SHELL");
    }
}
