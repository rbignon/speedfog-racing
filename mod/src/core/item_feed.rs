//! Race item feed: queued banners, timed reminder rows, the row of the item
//! held, and the ink timer.
//!
//! Pure timing, nothing reads the clock: banners run on wall time (`now`),
//! the reminder rows and the ink on the play clock (`play`, see
//! `core::play_clock`), so a load does not eat their time.

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

/// A row of the race panel: icon, text and colour family.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedRow {
    pub icon: String,
    pub text: String,
    pub tone: FeedTone,
}

/// A timed row of the race panel.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedReminder {
    pub row: FeedRow,
    /// End on the play clock.
    pub ends_at: Duration,
}

/// The ink: waiting for a zone with unused exits, or running to its end.
#[derive(Debug, Clone, PartialEq)]
enum Ink {
    Pending {
        row: Option<FeedRow>,
        duration: Duration,
    },
    Running {
        row: Option<FeedRow>,
        /// End on the play clock.
        ends_at: Duration,
    },
}

/// The race item held: a row with no countdown, shown while its goods is in
/// the inventory.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedHeld {
    pub key: String,
    pub icon: String,
    pub text: String,
}

#[derive(Debug, Default)]
pub struct ItemFeed {
    /// Banner on screen and when it started; `None` implies an empty queue.
    current: Option<(FeedBanner, Instant)>,
    queue: VecDeque<FeedBanner>,
    reminders: Vec<FeedReminder>,
    held: Option<FeedHeld>,
    ink: Option<Ink>,
}

impl ItemFeed {
    pub const BANNER_DURATION: Duration = Duration::from_secs(4);
    /// A banner fades in over its first moments and out over its last ones.
    pub const BANNER_FADE_IN: Duration = Duration::from_millis(250);
    pub const BANNER_FADE_OUT: Duration = Duration::from_millis(500);

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

    /// Drop the expired banner and start the next one at `now`; prune the
    /// reminders ended at `play`.
    pub fn advance(&mut self, now: Instant, play: Duration) {
        if let Some((_, started)) = &self.current {
            if now.saturating_duration_since(*started) >= Self::BANNER_DURATION {
                self.current = self.queue.pop_front().map(|b| (b, now));
            }
        }
        self.reminders.retain(|r| r.ends_at > play);
        if matches!(&self.ink, Some(Ink::Running { ends_at, .. }) if *ends_at <= play) {
            self.ink = None;
        }
    }

    /// Banner on screen, if any (as of the last `advance`).
    pub fn banner(&self) -> Option<&FeedBanner> {
        self.current.as_ref().map(|(b, _)| b)
    }

    /// Opacity of the banner on screen at `now`, 0 to 1: rising over
    /// `BANNER_FADE_IN`, falling over the last `BANNER_FADE_OUT`.
    pub fn banner_alpha(&self, now: Instant) -> f32 {
        let Some((_, started)) = &self.current else {
            return 0.0;
        };
        let shown = now.saturating_duration_since(*started);
        let rising = shown.as_secs_f32() / Self::BANNER_FADE_IN.as_secs_f32();
        let left = Self::BANNER_DURATION.saturating_sub(shown);
        let falling = left.as_secs_f32() / Self::BANNER_FADE_OUT.as_secs_f32();
        rising.min(falling).clamp(0.0, 1.0)
    }

    /// Add a reminder row running `duration` from `play`; a second one with
    /// the same text keeps the latest end.
    pub fn add_reminder(
        &mut self,
        icon: String,
        text: String,
        tone: FeedTone,
        duration: Duration,
        play: Duration,
    ) {
        let ends_at = play + duration;
        if let Some(existing) = self.reminders.iter_mut().find(|r| r.row.text == text) {
            if ends_at > existing.ends_at {
                existing.ends_at = ends_at;
                existing.row.icon = icon;
                existing.row.tone = tone;
            }
        } else {
            self.reminders.push(FeedReminder {
                row: FeedRow { icon, text, tone },
                ends_at,
            });
        }
    }

    /// Live rows at `play` with their time left: the timed reminders, then
    /// the ink's row (`None` while it waits for a zone, its time left while
    /// it runs). Expired ones are skipped.
    pub fn reminders(&self, play: Duration) -> impl Iterator<Item = (&FeedRow, Option<Duration>)> {
        let timed = self.reminders.iter().filter_map(move |r| {
            r.ends_at
                .checked_sub(play)
                .filter(|left| !left.is_zero())
                .map(|left| (&r.row, Some(left)))
        });
        let ink = self.ink.as_ref().and_then(move |ink| match ink {
            Ink::Pending { row, .. } => row.as_ref().map(|row| (row, None)),
            Ink::Running { row, ends_at } => row.as_ref().and_then(|row| {
                ends_at
                    .checked_sub(play)
                    .filter(|left| !left.is_zero())
                    .map(|left| (row, Some(left)))
            }),
        });
        timed.chain(ink)
    }

    /// Show (or stop showing) the held item row.
    pub fn set_held(&mut self, held: Option<FeedHeld>) {
        self.held = held;
    }

    pub fn held(&self) -> Option<&FeedHeld> {
        self.held.as_ref()
    }

    /// An ink hit. Running: the later end wins. Pending: nothing changes.
    /// Otherwise it runs for `duration` from `play` when `start`, else it
    /// waits (`start_pending_ink`) with its row and duration.
    pub fn hit_ink(
        &mut self,
        row: Option<FeedRow>,
        duration: Duration,
        start: bool,
        play: Duration,
    ) {
        let ends_at = play + duration;
        match &mut self.ink {
            Some(Ink::Pending { .. }) => {}
            Some(Ink::Running { ends_at: end, .. }) if play < *end => {
                if ends_at > *end {
                    *end = ends_at;
                }
            }
            _ if start => self.ink = Some(Ink::Running { row, ends_at }),
            _ => self.ink = Some(Ink::Pending { row, duration }),
        }
    }

    /// Run the pending ink from `play`; true when there was one.
    pub fn start_pending_ink(&mut self, play: Duration) -> bool {
        let Some(Ink::Pending { row, duration }) = self.ink.take() else {
            return false;
        };
        self.ink = Some(Ink::Running {
            row,
            ends_at: play + duration,
        });
        true
    }

    pub fn ink_pending(&self) -> bool {
        matches!(self.ink, Some(Ink::Pending { .. }))
    }

    pub fn ink_active(&self, play: Duration) -> bool {
        matches!(&self.ink, Some(Ink::Running { ends_at, .. }) if play < *ends_at)
    }

    /// Forget a pending ink (the run is over); a running one plays out.
    pub fn drop_pending_ink(&mut self) {
        if self.ink_pending() {
            self.ink = None;
        }
    }

    /// Drop the reminder rows, the held row and the ink; banners play on.
    pub fn clear_timers(&mut self) {
        self.reminders.clear();
        self.held = None;
        self.ink = None;
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

    fn shield() -> FeedHeld {
        FeedHeld {
            key: "shield".into(),
            icon: "shield".into(),
            text: "Shield".into(),
        }
    }

    #[test]
    fn banner_fades_in_then_out() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        assert_eq!(feed.banner_alpha(t0), 0.0);
        feed.push_banner(banner("a"), t0);
        assert_eq!(feed.banner_alpha(t0), 0.0);
        let half_in = ItemFeed::BANNER_FADE_IN / 2;
        assert!((feed.banner_alpha(t0 + half_in) - 0.5).abs() < 1e-3);
        assert_eq!(feed.banner_alpha(t0 + ItemFeed::BANNER_FADE_IN), 1.0);
        let half_out = ItemFeed::BANNER_DURATION - ItemFeed::BANNER_FADE_OUT / 2;
        assert!((feed.banner_alpha(t0 + half_out) - 0.5).abs() < 1e-3);
        assert_eq!(feed.banner_alpha(t0 + ItemFeed::BANNER_DURATION), 0.0);
    }

    #[test]
    fn clear_timers_drops_the_held_row() {
        let mut feed = ItemFeed::new();
        feed.set_held(Some(shield()));
        feed.clear_timers();
        assert_eq!(feed.held(), None);
    }

    #[test]
    fn banners_queue_one_duration_each() {
        let t0 = Instant::now();
        let d = ItemFeed::BANNER_DURATION;
        let just = Duration::from_millis(1);
        let mut feed = ItemFeed::new();
        for t in ["a", "b", "c"] {
            feed.push_banner(banner(t), t0);
        }
        for (at, expected) in [
            (Duration::ZERO, "A"),
            (d - just, "A"),
            (d, "B"),
            (d * 2 - just, "B"),
            (d * 2, "C"),
        ] {
            feed.advance(t0 + at, Duration::ZERO);
            assert_eq!(feed.banner().unwrap().title, expected, "at +{at:?}");
        }
        feed.advance(t0 + d * 3, Duration::ZERO);
        assert!(feed.banner().is_none());
    }

    #[test]
    fn a_banner_pushed_while_idle_starts_now() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        let d = ItemFeed::BANNER_DURATION;
        feed.push_banner(banner("a"), t0);
        feed.advance(t0 + d + secs(1), Duration::ZERO);
        assert!(feed.banner().is_none());
        let t1 = t0 + secs(20);
        feed.push_banner(banner("b"), t1);
        feed.advance(t1 + d - Duration::from_millis(1), Duration::ZERO);
        assert_eq!(feed.banner().unwrap().title, "B");
        feed.advance(t1 + d, Duration::ZERO);
        assert!(feed.banner().is_none());
    }

    #[test]
    fn reminder_with_the_same_text_keeps_the_latest_end() {
        let mut feed = ItemFeed::new();
        let at = Duration::ZERO;
        feed.add_reminder("i".into(), "Fat-roll".into(), FeedTone::Malus, secs(15), at);
        feed.add_reminder(
            "i".into(),
            "Fat-roll".into(),
            FeedTone::Malus,
            secs(15),
            at + secs(5),
        );
        // A shorter later copy must not shorten the row.
        feed.add_reminder(
            "i".into(),
            "Fat-roll".into(),
            FeedTone::Malus,
            secs(1),
            at + secs(6),
        );
        let rows: Vec<_> = feed.reminders(at + secs(10)).collect();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].1, Some(secs(10)));
        // Its end is the latest one: gone 10 s on.
        assert_eq!(feed.reminders(at + secs(20)).count(), 0);
        assert_eq!(feed.reminders(at + secs(19)).count(), 1);
    }

    #[test]
    fn expired_reminders_disappear() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        let at = Duration::ZERO;
        feed.add_reminder("i".into(), "a".into(), FeedTone::Gain, secs(5), at);
        feed.add_reminder("i".into(), "b".into(), FeedTone::Gain, secs(15), at);
        let texts = |feed: &ItemFeed, play| {
            feed.reminders(play)
                .map(|(r, _)| r.text.clone())
                .collect::<Vec<_>>()
        };
        assert_eq!(texts(&feed, at + secs(4)), ["a", "b"]);
        assert_eq!(texts(&feed, at + secs(5)), ["b"]);
        feed.advance(t0, at + secs(20));
        assert!(feed.reminders.is_empty());
    }

    #[test]
    fn reminders_count_play_time() {
        let t0 = Instant::now();
        let mut feed = ItemFeed::new();
        feed.add_reminder(
            "i".into(),
            "Slowed".into(),
            FeedTone::Malus,
            secs(15),
            Duration::ZERO,
        );
        // A minute of wall time, five seconds of it played.
        feed.advance(t0 + secs(60), secs(5));
        let left: Vec<_> = feed.reminders(secs(5)).map(|(_, left)| left).collect();
        assert_eq!(left, [Some(secs(10))]);
    }

    fn ink_row() -> Option<FeedRow> {
        Some(FeedRow {
            icon: "ink".into(),
            text: "Ink".into(),
            tone: FeedTone::Malus,
        })
    }

    #[test]
    fn ink_keeps_the_latest_end() {
        let mut feed = ItemFeed::new();
        let at = Duration::ZERO;
        assert!(!feed.ink_active(at));
        feed.hit_ink(None, secs(15), true, at);
        feed.hit_ink(None, secs(15), true, at + secs(10));
        feed.hit_ink(None, secs(1), true, at + secs(11));
        assert!(feed.ink_active(at + secs(24)));
        assert!(!feed.ink_active(at + secs(25)));
        feed.clear();
        assert!(!feed.ink_active(at + secs(12)));
    }

    #[test]
    fn a_second_ink_while_running_keeps_the_later_end() {
        let mut feed = ItemFeed::new();
        feed.hit_ink(ink_row(), secs(30), true, secs(0));
        // A hit that waits for a zone is still a running ink's extension.
        feed.hit_ink(ink_row(), secs(30), false, secs(10));
        assert!(!feed.ink_pending());
        assert!(feed.ink_active(secs(39)));
        assert!(!feed.ink_active(secs(40)));
        // A shorter one never shortens it.
        feed.hit_ink(ink_row(), secs(5), true, secs(12));
        assert!(feed.ink_active(secs(39)));
        assert_eq!(feed.reminders(secs(30)).count(), 1);
    }

    #[test]
    fn a_second_ink_while_pending_changes_nothing() {
        let mut feed = ItemFeed::new();
        feed.hit_ink(ink_row(), secs(30), false, secs(0));
        feed.hit_ink(None, secs(10), true, secs(5));
        assert!(feed.ink_pending());
        assert!(!feed.ink_active(secs(6)));
        assert!(feed.start_pending_ink(secs(8)));
        assert!(feed.ink_active(secs(37)));
        assert!(!feed.ink_active(secs(38)));
        assert_eq!(feed.reminders(secs(8)).count(), 1);
        assert!(!feed.start_pending_ink(secs(9)));
    }

    #[test]
    fn a_pending_ink_row_has_no_time_left() {
        let mut feed = ItemFeed::new();
        feed.add_reminder(
            "i".into(),
            "Slowed".into(),
            FeedTone::Malus,
            secs(15),
            secs(0),
        );
        feed.hit_ink(ink_row(), secs(30), false, secs(0));
        let rows: Vec<_> = feed
            .reminders(secs(3))
            .map(|(row, left)| (row.text.clone(), left))
            .collect();
        assert_eq!(
            rows,
            [("Slowed".into(), Some(secs(12))), ("Ink".into(), None)]
        );
        feed.start_pending_ink(secs(3));
        let left: Vec<_> = feed.reminders(secs(4)).map(|(_, left)| left).collect();
        assert_eq!(left, [Some(secs(11)), Some(secs(29))]);
    }

    #[test]
    fn title_is_uppercased_on_receipt() {
        assert_eq!(banner("Red Shell").title, "RED SHELL");
    }
}
