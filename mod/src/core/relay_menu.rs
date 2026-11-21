//! Relay races: the baton key. One key does everything: the holder's press
//! opens a menu of the teammates, a tap moves the highlight, a hold of
//! `HOLD_TO_CONFIRM` confirms it; a waiting runner holds the same key to take
//! a free baton. Pure: the shell feeds the key's state every frame and the
//! machine (`RaceMachine::maintain_relay_key`) decides what a key event is
//! worth. Nothing is drawn here.

use std::time::{Duration, Instant};

use crate::core::protocol::{ParticipantStatus, RelayInfo, RelayMember};

/// How long the key is held to confirm a handoff or a take.
pub const HOLD_TO_CONFIRM: Duration = Duration::from_secs(1);
/// The open menu closes by itself this long after the last press or release
/// while the key is up.
pub const MENU_AUTO_CLOSE: Duration = Duration::from_secs(5);

/// A key held down for `HOLD_TO_CONFIRM`.
#[derive(Debug, Default)]
pub struct HoldKey {
    since: Option<Instant>,
    fired: bool,
    /// The key was already down when the hold became possible: it must be
    /// released before a new hold counts.
    blocked: bool,
}

impl HoldKey {
    /// Feed the key's state for this frame (repeated downs are the same
    /// hold). True once per hold, on the first frame the key has been down
    /// `HOLD_TO_CONFIRM`; a release arms it again.
    pub fn update(&mut self, down: bool, now: Instant) -> bool {
        if self.blocked {
            if down {
                return false;
            }
            self.blocked = false;
        }
        if !down {
            self.since = None;
            self.fired = false;
            return false;
        }
        let since = *self.since.get_or_insert(now);
        if !self.fired && now.saturating_duration_since(since) >= HOLD_TO_CONFIRM {
            self.fired = true;
            return true;
        }
        false
    }

    /// How far the hold is, 0 to 1.
    pub fn progress(&self, now: Instant) -> f32 {
        self.since.map_or(0.0, |since| {
            (now.saturating_duration_since(since).as_secs_f32() / HOLD_TO_CONFIRM.as_secs_f32())
                .min(1.0)
        })
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }

    /// The hold is not possible now: forget it, and when the key is `down`
    /// ignore that press until it is released (a hold that started before
    /// it became possible never counts).
    pub fn suspend(&mut self, down: bool) {
        self.reset();
        self.blocked = down;
    }
}

/// What a frame of the menu produced.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MenuEvent {
    None,
    /// The menu just opened on the first teammate.
    Opened,
    /// A tap moved the highlight on.
    Next,
    /// A hold confirmed the highlighted teammate (index among the eligible);
    /// the menu closed.
    Confirmed(usize),
    /// The menu closed by itself.
    Closed,
}

/// The holder's menu: its state only, the machine owns the list.
#[derive(Debug, Default)]
pub struct HandoffMenu {
    open: bool,
    selected: usize,
    /// The press in progress started at.
    pressed_at: Option<Instant>,
    /// The press in progress can no longer tap or confirm (it opened the
    /// menu, or what it pointed at is gone).
    spent: bool,
    /// The key was down when the menu became impossible or after a confirm:
    /// ignored until released.
    blocked: bool,
    last_input: Option<Instant>,
}

impl HandoffMenu {
    /// Feed the key's state and the number of teammates that can receive.
    /// A press on a closed menu opens it on index 0 and is spent: it neither
    /// advances nor confirms. A release before `HOLD_TO_CONFIRM` is a tap
    /// (next, wrapping); a hold confirms once and closes; with nobody
    /// eligible nothing is ever confirmed. A press already down when the
    /// menu was not possible does not open it.
    pub fn update(&mut self, down: bool, eligible: usize, now: Instant) -> MenuEvent {
        if self.blocked {
            if down {
                return MenuEvent::None;
            }
            self.blocked = false;
        }
        if self.selected >= eligible {
            self.selected = 0;
        }
        if !self.open {
            if down && self.pressed_at.is_none() {
                self.open = true;
                self.selected = 0;
                self.pressed_at = Some(now);
                self.spent = true;
                self.last_input = Some(now);
                return MenuEvent::Opened;
            }
            if !down {
                self.pressed_at = None;
            }
            return MenuEvent::None;
        }
        match (down, self.pressed_at) {
            (true, None) => {
                self.pressed_at = Some(now);
                // A press that began with nobody highlighted never confirms
                // someone who became eligible during it.
                self.spent = eligible == 0;
                self.last_input = Some(now);
            }
            (true, Some(since)) => {
                if !self.spent && now.saturating_duration_since(since) >= HOLD_TO_CONFIRM {
                    self.spent = true;
                    if eligible > 0 {
                        let index = self.selected;
                        self.close();
                        self.blocked = true;
                        return MenuEvent::Confirmed(index);
                    }
                }
            }
            (false, Some(since)) => {
                self.pressed_at = None;
                self.last_input = Some(now);
                let tap = now.saturating_duration_since(since) < HOLD_TO_CONFIRM;
                if !self.spent && tap && eligible > 0 {
                    self.selected = (self.selected + 1) % eligible;
                    return MenuEvent::Next;
                }
            }
            (false, None) => {
                if self
                    .last_input
                    .is_some_and(|at| now.saturating_duration_since(at) >= MENU_AUTO_CLOSE)
                {
                    self.close();
                    return MenuEvent::Closed;
                }
            }
        }
        MenuEvent::None
    }

    pub fn is_open(&self) -> bool {
        self.open
    }

    /// Index of the highlighted teammate among the eligible.
    pub fn selected(&self) -> usize {
        self.selected
    }

    pub fn select(&mut self, index: usize) {
        self.selected = index;
    }

    /// The press in progress, if any, can no longer tap or confirm: it was
    /// aimed at a highlight that is gone.
    pub fn spend_press(&mut self) {
        self.spent = true;
    }

    /// How far the confirming hold is, 0 to 1.
    pub fn progress(&self, now: Instant) -> f32 {
        match self.pressed_at {
            Some(since) if self.open && !self.spent => {
                (now.saturating_duration_since(since).as_secs_f32() / HOLD_TO_CONFIRM.as_secs_f32())
                    .min(1.0)
            }
            _ => 0.0,
        }
    }

    pub fn close(&mut self) {
        self.open = false;
        self.selected = 0;
        self.pressed_at = None;
        self.spent = false;
        self.last_input = None;
    }

    /// The menu is not possible now: close it, and when the key is `down`
    /// ignore that press until it is released.
    pub fn suspend(&mut self, down: bool) {
        self.close();
        self.blocked = down;
    }
}

/// Why a teammate cannot receive the baton, as the server judges it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Unavailable {
    /// Finished, abandoned or disqualified.
    Out,
    /// A status this mod does not know: nothing is offered on it.
    Unknown,
    NotInGame,
    /// Not validated: it may simply not have reported yet, so the row never
    /// says its save was refused.
    NoFreshSave,
    AtCap,
}

impl Unavailable {
    pub fn text(self) -> &'static str {
        match self {
            Unavailable::Out => "out of the race",
            Unavailable::Unknown => "status unknown",
            Unavailable::NotInGame => "not in game",
            Unavailable::NoFreshSave => "no fresh save",
            Unavailable::AtCap => "at the cap",
        }
    }
}

/// Why `member` cannot receive the baton, in the order of the server's
/// `receive_refusal` for a handoff target: out, then not online or not
/// ready, then not validated, then at the cap. It reads the server's echo.
pub fn availability(member: &RelayMember, cap: u32) -> Option<Unavailable> {
    match member.status {
        ParticipantStatus::Finished
        | ParticipantStatus::Abandoned
        | ParticipantStatus::Disqualified => return Some(Unavailable::Out),
        ParticipantStatus::Unknown => return Some(Unavailable::Unknown),
        ParticipantStatus::Registered | ParticipantStatus::Ready | ParticipantStatus::Playing => {}
    }
    if !member.online || !member.ready {
        Some(Unavailable::NotInGame)
    } else if !member.validated {
        Some(Unavailable::NoFreshSave)
    } else if member.zones >= cap {
        Some(Unavailable::AtCap)
    } else {
        None
    }
}

/// One teammate of the menu, its strings built once per `RelayInfo`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuRow {
    pub participant_id: String,
    pub name: String,
    /// The counter as the server gives it: "2/5 zones".
    pub counter: String,
    /// `None`: the teammate can receive.
    pub unavailable: Option<Unavailable>,
}

/// The menu's rows: every member but the runner (`me`), in `members` order.
pub fn build_rows(relay: &RelayInfo, me: Option<&str>) -> Vec<MenuRow> {
    relay
        .members
        .iter()
        .filter(|member| Some(member.participant_id.as_str()) != me)
        .map(|member| MenuRow {
            participant_id: member.participant_id.clone(),
            name: member.name.clone(),
            counter: format!("{}/{} zones", member.zones, relay.cap),
            unavailable: availability(member, relay.cap),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ms(v: u64) -> Duration {
        Duration::from_millis(v)
    }

    fn member(online: bool, ready: bool, validated: bool, zones: u32) -> RelayMember {
        RelayMember {
            participant_id: "p2".to_string(),
            name: "Kahleeya".to_string(),
            zones,
            status: ParticipantStatus::Playing,
            online,
            ready,
            validated,
        }
    }

    #[test]
    fn a_tap_moves_on_and_a_one_second_hold_confirms() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        assert_eq!(menu.update(true, 2, t0), MenuEvent::Opened);
        assert_eq!(menu.update(true, 2, t0 + ms(1500)), MenuEvent::None); // the opening press never confirms
        assert_eq!(menu.update(false, 2, t0 + ms(1600)), MenuEvent::None); // nor advances
        menu.update(true, 2, t0 + ms(2000));
        assert_eq!(menu.update(false, 2, t0 + ms(2200)), MenuEvent::Next);
        assert_eq!(menu.selected(), 1);
        menu.update(true, 2, t0 + ms(3000));
        assert_eq!(menu.update(true, 2, t0 + ms(3999)), MenuEvent::None);
        assert_eq!(menu.update(true, 2, t0 + ms(4000)), MenuEvent::Confirmed(1));
        assert!(!menu.is_open());
    }

    #[test]
    fn closes_by_itself_five_seconds_after_the_last_input() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 2, t0);
        menu.update(false, 2, t0 + ms(100));
        assert_eq!(menu.update(false, 2, t0 + ms(5099)), MenuEvent::None);
        assert_eq!(menu.update(false, 2, t0 + ms(5100)), MenuEvent::Closed);
    }

    #[test]
    fn the_bar_fills_over_the_hold() {
        let t0 = Instant::now();
        let mut key = HoldKey::default();
        assert!(!key.update(true, t0));
        assert!((key.progress(t0 + ms(500)) - 0.5).abs() < 0.01);
        assert!(key.update(true, t0 + ms(1000)));
        assert!(!key.update(true, t0 + ms(1500))); // once per hold
        key.update(false, t0 + ms(1600));
        assert_eq!(key.progress(t0 + ms(1700)), 0.0);
    }

    #[test]
    fn a_hold_released_just_short_confirms_nothing_and_a_full_one_does() {
        let t0 = Instant::now();
        let mut key = HoldKey::default();
        key.update(true, t0);
        assert!(!key.update(true, t0 + ms(999)));
        assert!(!key.update(false, t0 + ms(999)));
        // A new hold starts from its own press.
        assert!(!key.update(true, t0 + ms(1500)));
        assert!(key.update(true, t0 + ms(2500)));
    }

    #[test]
    fn a_hold_started_while_suspended_counts_only_after_a_release() {
        let t0 = Instant::now();
        let mut key = HoldKey::default();
        key.suspend(true);
        assert!(!key.update(true, t0));
        assert!(!key.update(true, t0 + ms(5000)), "held from before");
        key.update(false, t0 + ms(5100));
        key.update(true, t0 + ms(5200));
        assert!(key.update(true, t0 + ms(6200)));
        // Suspended with the key up: the next press counts at once.
        key.suspend(false);
        key.update(true, t0 + ms(7000));
        assert!(key.update(true, t0 + ms(8000)));
    }

    #[test]
    fn a_press_held_from_before_never_opens_the_menu() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.suspend(true);
        assert_eq!(menu.update(true, 2, t0), MenuEvent::None);
        assert_eq!(menu.update(true, 2, t0 + ms(3000)), MenuEvent::None);
        assert!(!menu.is_open());
        menu.update(false, 2, t0 + ms(3100));
        assert_eq!(menu.update(true, 2, t0 + ms(3200)), MenuEvent::Opened);
    }

    #[test]
    fn os_key_repeat_is_one_press_not_taps() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 3, t0);
        menu.update(false, 3, t0 + ms(50));
        menu.update(true, 3, t0 + ms(100));
        // Repeated downs every 30 ms for 500 ms, then the release: one tap.
        for step in 1..=16 {
            assert_eq!(
                menu.update(true, 3, t0 + ms(100 + step * 30)),
                MenuEvent::None
            );
        }
        assert_eq!(menu.update(false, 3, t0 + ms(700)), MenuEvent::Next);
        assert_eq!(menu.selected(), 1);
    }

    #[test]
    fn a_hold_confirms_once_and_the_held_key_does_not_reopen_the_menu() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 1, t0);
        menu.update(false, 1, t0 + ms(100));
        menu.update(true, 1, t0 + ms(200));
        assert_eq!(menu.update(true, 1, t0 + ms(1200)), MenuEvent::Confirmed(0));
        assert_eq!(menu.update(true, 1, t0 + ms(1300)), MenuEvent::None);
        assert_eq!(menu.update(true, 1, t0 + ms(2500)), MenuEvent::None);
        assert!(!menu.is_open());
        assert_eq!(menu.update(false, 1, t0 + ms(2600)), MenuEvent::None);
        assert_eq!(menu.update(true, 1, t0 + ms(2700)), MenuEvent::Opened);
    }

    #[test]
    fn a_menu_without_an_eligible_teammate_confirms_nothing() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        assert_eq!(menu.update(true, 0, t0), MenuEvent::Opened);
        menu.update(false, 0, t0 + ms(100));
        menu.update(true, 0, t0 + ms(200));
        assert_eq!(menu.update(true, 0, t0 + ms(2200)), MenuEvent::None);
        assert_eq!(menu.update(false, 0, t0 + ms(2300)), MenuEvent::None);
        assert!(menu.is_open());
        assert_eq!(menu.update(false, 0, t0 + ms(7299)), MenuEvent::None);
        assert_eq!(menu.update(false, 0, t0 + ms(7300)), MenuEvent::Closed);
    }

    #[test]
    fn the_selection_wraps() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 2, t0);
        menu.update(false, 2, t0 + ms(50));
        for (i, at) in [1000u64, 2000].into_iter().enumerate() {
            menu.update(true, 2, t0 + ms(at));
            assert_eq!(menu.update(false, 2, t0 + ms(at + 100)), MenuEvent::Next);
            assert_eq!(menu.selected(), (i + 1) % 2);
        }
    }

    #[test]
    fn a_press_spent_by_a_vanished_highlight_confirms_nothing() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 2, t0);
        menu.update(false, 2, t0 + ms(50));
        menu.update(true, 2, t0 + ms(100));
        menu.spend_press();
        assert_eq!(menu.update(true, 2, t0 + ms(1500)), MenuEvent::None);
        assert_eq!(menu.update(false, 2, t0 + ms(1600)), MenuEvent::None);
        assert_eq!(menu.selected(), 0);
    }

    #[test]
    fn availability_orders_its_reasons() {
        assert_eq!(
            availability(&member(false, true, true, 5), 5),
            Some(Unavailable::NotInGame)
        );
        assert_eq!(
            availability(&member(true, false, false, 0), 5),
            Some(Unavailable::NotInGame)
        );
        assert_eq!(
            availability(&member(true, true, false, 5), 5),
            Some(Unavailable::NoFreshSave)
        );
        assert_eq!(
            availability(&member(true, true, true, 5), 5),
            Some(Unavailable::AtCap)
        );
        assert_eq!(availability(&member(true, true, true, 4), 5), None);
    }

    #[test]
    fn an_out_or_unknown_member_is_never_offered() {
        for status in [
            ParticipantStatus::Finished,
            ParticipantStatus::Abandoned,
            ParticipantStatus::Disqualified,
        ] {
            let mut m = member(true, true, true, 0);
            m.status = status;
            assert_eq!(availability(&m, 5), Some(Unavailable::Out));
        }
        let mut m = member(true, true, true, 0);
        m.status = ParticipantStatus::Unknown;
        assert_eq!(availability(&m, 5), Some(Unavailable::Unknown));
    }

    #[test]
    fn a_press_begun_with_nobody_eligible_is_spent() {
        let t0 = Instant::now();
        let mut menu = HandoffMenu::default();
        menu.update(true, 0, t0);
        menu.update(false, 0, t0 + ms(100));
        menu.update(true, 0, t0 + ms(200));
        // Someone turns up during the press.
        assert_eq!(menu.update(true, 1, t0 + ms(1500)), MenuEvent::None);
        assert_eq!(menu.update(false, 1, t0 + ms(1600)), MenuEvent::None);
    }
}
