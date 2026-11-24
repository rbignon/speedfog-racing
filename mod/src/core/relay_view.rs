//! Relay races: what the overlay says about the baton. Pure: strings are
//! built once per received `RelayInfo` (and once per displayed second of an
//! offline holder's countdown) and cached; the drawing only reads them.
//! Nothing is measured or drawn here.

use std::time::Duration;

use crate::core::protocol::{ParticipantStatus, RelayInfo, RelayMember, RelayRole};
use crate::core::relay_menu::{availability, MENU_AUTO_CLOSE};

/// Title of the holder's menu.
pub const MENU_TITLE: &str = "PASS THE BATON";
/// Replaces a hold prompt or the menu's key hints while a request the
/// server has not answered is in flight.
pub const REQUEST_TEXT: &str = "Waiting for the server";
/// Replaces the take prompt while the runner is not yet ready to take.
pub const NOT_READY_TEXT: &str = "Not ready yet: wait at the Chapel.";
/// Replaces every key hint while the baton key is unbound (`relay = "none"`
/// in the config): the player is told what to do, no key is named.
pub const UNBOUND_TEXT: &str = "No baton key bound: set `relay` in the config";
/// The line under "BATON PASSED TO <RUNNER>" while the giver is on its way
/// back to the Chapel.
pub const RETURNING_TEXT: &str = "Returning to the Chapel of Anticipation...";
/// One pulse of a pulsing line: full, down to `PULSE_MIN`, full again.
pub const PULSE_PERIOD: Duration = Duration::from_millis(1200);
/// The faintest a pulsing line gets: it never vanishes.
pub const PULSE_MIN: f32 = 0.35;
/// Stands for a name the server left empty or did not send.
const UNKNOWN_NAME: &str = "A teammate";
const UNKNOWN_HOLDER: &str = "The holder";

/// Color family of a block's title; the drawing maps it to the overlay's
/// colors (fog: text, brass: gold, ember: danger, verdigris: success).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BlockTone {
    Fog,
    Brass,
    Ember,
    Verdigris,
}

/// The permanent top-centre banner of a waiting runner.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WaitBanner {
    pub tone: BlockTone,
    pub title: String,
    pub line: String,
    /// May be empty: the drawing then draws no detail line.
    pub detail: String,
    /// The detail is the hold prompt: the hold's progress bar goes under it.
    pub hold_bar: bool,
}

/// One teammate of the menu as it reads on screen.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuRow {
    pub participant_id: String,
    pub name: String,
    /// The counter ("2/5 zones") or, for one who cannot receive, the reason.
    pub right: String,
    pub available: bool,
}

/// Everything the overlay says about a relay runner's baton. The default is
/// the empty view: the renderer draws no relay line, banner or menu.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RelayView {
    /// Who holds the baton on the BATON line: a name, "you", "free" or
    /// "nobody". Empty when nothing relay-specific is shown.
    pub baton_who: String,
    /// The runner's own counter on that line ("you 2/5 zones" while it
    /// waits, "3/5 zones" as holder).
    pub baton_count: String,
    /// The key hint at the end of that line ("F8 pass", "F8 take"), or empty.
    pub baton_hint: String,
    pub wait: Option<WaitBanner>,
    /// The menu's teammates, in the server's order; drawn while it is open.
    pub rows: Vec<MenuRow>,
    pub menu_hint: String,
    /// Why the menu has nobody to pick, or empty.
    pub menu_note: String,
}

fn gone(status: ParticipantStatus) -> bool {
    matches!(
        status,
        ParticipantStatus::Finished
            | ParticipantStatus::Abandoned
            | ParticipantStatus::Disqualified
    )
}

fn name_of(member: &RelayMember) -> &str {
    if member.name.trim().is_empty() {
        UNKNOWN_NAME
    } else {
        &member.name
    }
}

fn counter(member: &RelayMember, cap: u32) -> String {
    format!("{}/{} zones", member.zones, cap)
}

/// The giver's banner from the flip until it is blocked (`PassedBanner`):
/// the recipient's name in the title, the return to the Chapel below it.
pub fn passed_banner(to_name: &str) -> WaitBanner {
    WaitBanner {
        tone: BlockTone::Brass,
        title: format!("BATON PASSED TO {}", to_name.to_uppercase()),
        line: RETURNING_TEXT.to_string(),
        detail: String::new(),
        hold_bar: false,
    }
}

/// Opacity of a pulsing line `elapsed` after it appeared: 1 at the start of
/// every `PULSE_PERIOD`, `PULSE_MIN` halfway through, a smooth cosine in
/// between.
pub fn pulse_alpha(elapsed: Duration) -> f32 {
    let phase = (elapsed.as_secs_f32() / PULSE_PERIOD.as_secs_f32()).fract();
    let wave = 0.5 + 0.5 * (phase * std::f32::consts::TAU).cos();
    PULSE_MIN + (1.0 - PULSE_MIN) * wave
}

/// "9 of 12" from the displayed layer and the total; `None` unless both are
/// plausible.
fn layer_text(layer: Option<(i32, i32)>) -> Option<String> {
    layer
        .filter(|&(shown, total)| shown >= 1 && total >= 1 && shown <= total)
        .map(|(shown, total)| format!("Zone {shown} of {total}"))
}

/// Build the view of a runner. `role` is the machine's `relay_role()`
/// (`Holder` while a take received runs, whatever `info.role` reads),
/// `me` the runner's participant id, `layer` the displayed layer and the
/// total, `free_in` the seconds before the baton can be taken, counted
/// down locally, `key` the label of the baton key, `None` when it is unbound. The team not live (setup
/// included), the runner out and an unknown role give the empty view: an
/// unknown value is never read as a decision.
pub fn build(
    info: &RelayInfo,
    role: RelayRole,
    me: &str,
    layer: Option<(i32, i32)>,
    free_in: Option<u32>,
    key: Option<&str>,
) -> RelayView {
    let live = matches!(
        info.team_status,
        ParticipantStatus::Ready | ParticipantStatus::Playing
    );
    let me_entry = info.members.iter().find(|m| m.participant_id == me);
    if !live || me_entry.is_some_and(|m| gone(m.status)) {
        return RelayView::default();
    }
    match role {
        RelayRole::Holder => holder_view(info, me, me_entry, key),
        RelayRole::Waiting => waiting_view(info, me, me_entry, layer, free_in, key),
        RelayRole::Unknown => RelayView::default(),
    }
}

fn holder_view(
    info: &RelayInfo,
    me: &str,
    me_entry: Option<&RelayMember>,
    key: Option<&str>,
) -> RelayView {
    let mut view = RelayView {
        baton_who: "you".to_string(),
        baton_count: me_entry.map(|m| counter(m, info.cap)).unwrap_or_default(),
        ..RelayView::default()
    };
    // The server still reads the runner waiting: a take is in progress or
    // its confirmation window runs, and the menu is not possible yet.
    if info.role != RelayRole::Holder {
        return view;
    }
    view.baton_hint = key.map(|key| format!("{key} pass")).unwrap_or_default();
    view.rows = info
        .members
        .iter()
        .filter(|m| m.participant_id != me && !gone(m.status))
        .map(|m| {
            let reason = availability(m, info.cap);
            MenuRow {
                participant_id: m.participant_id.clone(),
                name: name_of(m).to_string(),
                right: reason.map_or_else(|| counter(m, info.cap), |r| r.text().to_string()),
                available: reason.is_none(),
            }
        })
        .collect();
    let close = format!("closes by itself after {} s", MENU_AUTO_CLOSE.as_secs());
    if view.rows.iter().any(|r| r.available) {
        view.menu_hint = match key {
            Some(key) => format!("{key} next   hold {key} to pass   {close}"),
            None => UNBOUND_TEXT.to_string(),
        };
    } else {
        view.menu_hint = close;
        view.menu_note = if view.rows.is_empty() {
            "No teammate can take the baton"
        } else {
            "Nobody can take the baton right now"
        }
        .to_string();
    }
    view
}

fn waiting_view(
    info: &RelayInfo,
    me: &str,
    me_entry: Option<&RelayMember>,
    layer: Option<(i32, i32)>,
    free_in: Option<u32>,
    key: Option<&str>,
) -> RelayView {
    let holder = info
        .holder_id
        .as_deref()
        .and_then(|id| info.members.iter().find(|m| m.participant_id == id));
    let holder_is_me = info.holder_id.as_deref() == Some(me);
    let holder_name = holder.map_or(UNKNOWN_HOLDER, name_of);
    let zone = info
        .zone_name
        .as_deref()
        .map(str::trim)
        .filter(|z| !z.is_empty());
    let free = free_in == Some(0);
    let mine = me_entry.map(|m| counter(m, info.cap));
    let mut view = RelayView {
        baton_who: if free {
            "free".to_string()
        } else if holder_is_me {
            "you".to_string()
        } else if info.holder_id.is_none() {
            "nobody".to_string()
        } else {
            holder_name.to_string()
        },
        baton_count: mine
            .as_ref()
            .map(|c| format!("you {c}"))
            .unwrap_or_default(),
        ..RelayView::default()
    };
    if free {
        // The server's own order of refusals for a take: not validated, then
        // at the cap.
        let (detail, hold_bar) = match me_entry {
            Some(m) if !m.validated => (
                "No fresh save: you cannot take the baton.".to_string(),
                false,
            ),
            Some(m) if m.zones >= info.cap => ("You are at your cap.".to_string(), false),
            // No key to hold: the prompt says so, with no bar.
            Some(_) if key.is_none() => (UNBOUND_TEXT.to_string(), false),
            Some(_) => {
                let key = key.unwrap_or_default();
                (
                    match zone {
                        Some(zone) => {
                            format!("Hold {key} to take the baton at the entrance of {zone}.")
                        }
                        None => format!("Hold {key} to take the baton."),
                    },
                    true,
                )
            }
            None => (String::new(), false),
        };
        if let (true, Some(key)) = (hold_bar, key) {
            view.baton_hint = format!("{key} take");
        }
        let line = if info.holder_id.is_none() {
            "The holder left the race".to_string()
        } else if !info.holder_online && !holder_is_me {
            format!("{holder_name} has been offline for over a minute")
        } else {
            "The handoff was not completed".to_string()
        };
        view.wait = Some(WaitBanner {
            tone: BlockTone::Verdigris,
            title: "THE BATON IS FREE".to_string(),
            line,
            detail,
            hold_bar,
        });
        return view;
    }
    let offline = !info.holder_online && info.holder_id.is_some() && !holder_is_me;
    view.wait = Some(if offline {
        WaitBanner {
            tone: BlockTone::Ember,
            title: format!("{} IS OFFLINE", holder_name.to_uppercase()),
            line: match free_in {
                Some(secs) => format!("The baton can be taken in {secs} s"),
                None => format!("{holder_name} is not in the game"),
            },
            detail: format!("It goes back to {holder_name} if they return before then."),
            hold_bar: false,
        }
    } else {
        let line = if holder_is_me {
            "The baton is with you".to_string()
        } else if info.holder_id.is_none() {
            "Nobody holds the baton".to_string()
        } else if let Some(zone) = zone {
            format!("{holder_name} is in {zone}")
        } else {
            format!("{holder_name} holds the baton")
        };
        let detail = match (layer_text(layer), mine.as_ref()) {
            (Some(layer), Some(c)) => format!("{layer}. You: {c}."),
            (Some(layer), None) => format!("{layer}."),
            (None, Some(c)) => format!("You: {c}."),
            (None, None) => String::new(),
        };
        WaitBanner {
            tone: BlockTone::Fog,
            title: "WAITING FOR THE BATON".to_string(),
            line,
            detail,
            hold_bar: false,
        }
    });
    view
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::protocol::{ParticipantStatus, RelayInfo, RelayRole};

    /// A team of five: Roger `p1` (the runner, 2 zones), Kahleeya `p2`
    /// (holder, 3), Gordychou `p3` (1), wospince `p4` (5, at the cap),
    /// Linlin_Tv `p5` (offline, not ready).
    fn info(role: &str, online: bool, free_in: Option<u32>) -> RelayInfo {
        serde_json::from_value(serde_json::json!({
            "team_id": "t1", "team_name": "Blue Team", "team_status": "playing", "cap": 5,
            "holder_id": "p2", "holder_online": online,
            "zone_name": "Leyndell, Royal Capital", "baton_free_in_s": free_in,
            "role": role, "gates_locked": false,
            "members": [
                {"participant_id": "p1", "name": "Roger", "zones": 2, "status": "playing", "online": true, "ready": true, "validated": true},
                {"participant_id": "p2", "name": "Kahleeya", "zones": 3, "status": "playing", "online": online, "ready": true, "validated": true},
                {"participant_id": "p3", "name": "Gordychou", "zones": 1, "status": "playing", "online": true, "ready": true, "validated": true},
                {"participant_id": "p4", "name": "wospince", "zones": 5, "status": "playing", "online": true, "ready": true, "validated": true},
                {"participant_id": "p5", "name": "Linlin_Tv", "zones": 0, "status": "playing", "online": false, "ready": false, "validated": true}
            ],
            "flags": {"lock_flag": 1050290500, "chapel_warp_flag": 1050290501, "warp_flag_base": 1050290510, "zone_flag_base": 1050294000, "travel_lock_flag": 1050290503, "roundtable_warp_flag": 1050290504, "token_flag_base": 1050297900, "token_bits": 24}
        }))
        .unwrap()
    }

    fn member<'a>(i: &'a mut RelayInfo, id: &str) -> &'a mut crate::core::protocol::RelayMember {
        i.members
            .iter_mut()
            .find(|m| m.participant_id == id)
            .unwrap()
    }

    fn wait_of(v: &RelayView) -> (BlockTone, &str, &str, &str, bool) {
        let w = v.wait.as_ref().unwrap();
        (w.tone, &w.title, &w.line, &w.detail, w.hold_bar)
    }

    const LAYER: Option<(i32, i32)> = Some((9, 12));

    #[test]
    fn a_waiting_runner_reads_who_holds_the_baton_and_where() {
        let v = build(
            &info("waiting", true, None),
            RelayRole::Waiting,
            "p1",
            LAYER,
            None,
            Some("F8"),
        );
        let w = v.wait.unwrap();
        assert_eq!(
            (w.tone, w.title.as_str()),
            (BlockTone::Fog, "WAITING FOR THE BATON")
        );
        assert_eq!(w.line, "Kahleeya is in Leyndell, Royal Capital");
        assert_eq!(w.detail, "Zone 9 of 12. You: 2/5 zones.");
        assert_eq!(
            (
                v.baton_who.as_str(),
                v.baton_count.as_str(),
                v.baton_hint.as_str()
            ),
            ("Kahleeya", "you 2/5 zones", "")
        );
    }

    #[test]
    fn an_offline_holder_counts_down_then_frees_the_baton() {
        let w = build(
            &info("waiting", false, Some(60)),
            RelayRole::Waiting,
            "p1",
            LAYER,
            Some(42),
            Some("F8"),
        )
        .wait
        .unwrap();
        assert_eq!(
            (w.tone, w.title.as_str()),
            (BlockTone::Ember, "KAHLEEYA IS OFFLINE")
        );
        assert_eq!(w.line, "The baton can be taken in 42 s");
        assert_eq!(
            w.detail,
            "It goes back to Kahleeya if they return before then."
        );
        let w = build(
            &info("waiting", false, Some(60)),
            RelayRole::Waiting,
            "p1",
            LAYER,
            Some(0),
            Some("F8"),
        )
        .wait
        .unwrap();
        assert_eq!(
            (w.tone, w.title.as_str(), w.hold_bar),
            (BlockTone::Verdigris, "THE BATON IS FREE", true)
        );
        assert_eq!(w.line, "Kahleeya has been offline for over a minute");
        assert_eq!(
            w.detail,
            "Hold F8 to take the baton at the entrance of Leyndell, Royal Capital."
        );
        let capped = build(
            &info("waiting", false, Some(0)),
            RelayRole::Waiting,
            "p4",
            LAYER,
            Some(0),
            Some("F8"),
        )
        .wait
        .unwrap();
        assert_eq!(
            (capped.detail.as_str(), capped.hold_bar),
            ("You are at your cap.", false)
        );
    }

    #[test]
    fn the_holder_gets_a_menu_and_a_key_hint() {
        let v = build(
            &info("holder", true, None),
            RelayRole::Holder,
            "p2",
            LAYER,
            None,
            Some("F7"),
        );
        assert!(v.wait.is_none());
        assert_eq!(
            (
                v.baton_who.as_str(),
                v.baton_count.as_str(),
                v.baton_hint.as_str()
            ),
            ("you", "3/5 zones", "F7 pass")
        );
        let rows: Vec<_> = v
            .rows
            .iter()
            .map(|r| (r.name.as_str(), r.right.as_str(), r.available))
            .collect();
        assert_eq!(
            rows,
            [
                ("Roger", "2/5 zones", true),
                ("Gordychou", "1/5 zones", true),
                ("wospince", "at the cap", false),
                ("Linlin_Tv", "not in game", false)
            ]
        );
        assert_eq!(
            v.menu_hint,
            "F7 next   hold F7 to pass   closes by itself after 5 s"
        );
    }

    #[test]
    fn a_holder_who_left_frees_the_baton_with_another_line() {
        let mut i = info("waiting", false, Some(0));
        member(&mut i, "p2").status = ParticipantStatus::Abandoned;
        i.holder_id = None;
        let v = build(&i, RelayRole::Waiting, "p1", LAYER, Some(0), Some("F8"));
        let (tone, title, line, detail, bar) = wait_of(&v);
        assert_eq!(
            (tone, title, line),
            (
                BlockTone::Verdigris,
                "THE BATON IS FREE",
                "The holder left the race"
            )
        );
        assert_eq!(
            (detail, bar),
            (
                "Hold F8 to take the baton at the entrance of Leyndell, Royal Capital.",
                true
            )
        );
        assert_eq!(v.baton_who, "free");
        assert_eq!(v.baton_hint, "F8 take");
    }

    #[test]
    fn an_unfinished_handoff_frees_the_baton() {
        let v = build(
            &info("waiting", true, Some(0)),
            RelayRole::Waiting,
            "p1",
            LAYER,
            Some(0),
            Some("F8"),
        );
        assert_eq!(wait_of(&v).2, "The handoff was not completed");
        assert_eq!(v.baton_who, "free");
        let mut i = info("waiting", true, Some(0));
        i.holder_id = Some("p1".to_string());
        let v = build(&i, RelayRole::Waiting, "p1", LAYER, Some(0), Some("F8"));
        assert_eq!(wait_of(&v).2, "The handoff was not completed");
    }

    #[test]
    fn nothing_shows_outside_a_live_team() {
        let mut setup = info("waiting", false, Some(0));
        setup.team_status = ParticipantStatus::Registered;
        setup.holder_id = None;
        for status in [
            ParticipantStatus::Registered,
            ParticipantStatus::Finished,
            ParticipantStatus::Abandoned,
            ParticipantStatus::Disqualified,
            ParticipantStatus::Unknown,
        ] {
            setup.team_status = status;
            for role in [RelayRole::Waiting, RelayRole::Holder] {
                let v = build(&setup, role, "p1", LAYER, Some(0), Some("F8"));
                assert_eq!(v, RelayView::default(), "{status:?} {role:?}");
            }
        }
        for status in [
            ParticipantStatus::Abandoned,
            ParticipantStatus::Disqualified,
        ] {
            let mut i = info("waiting", true, None);
            member(&mut i, "p1").status = status;
            assert_eq!(
                build(&i, RelayRole::Waiting, "p1", LAYER, None, Some("F8")),
                RelayView::default()
            );
        }
    }

    #[test]
    fn a_take_in_progress_reads_as_the_holder() {
        let mut i = info("waiting", true, Some(0));
        i.holder_id = Some("p1".to_string());
        let v = build(&i, RelayRole::Holder, "p1", LAYER, Some(0), Some("F8"));
        assert!(v.wait.is_none());
        assert_eq!(
            (v.baton_who.as_str(), v.baton_count.as_str()),
            ("you", "2/5 zones")
        );
        // The menu is not possible until the take is acknowledged.
        assert_eq!(
            (v.baton_hint.as_str(), v.rows.len(), v.menu_hint.as_str()),
            ("", 0, "")
        );
    }

    #[test]
    fn an_unknown_zone_drops_the_place() {
        let mut i = info("waiting", true, None);
        i.zone_name = None;
        let v = build(&i, RelayRole::Waiting, "p1", None, None, Some("F8"));
        assert_eq!(wait_of(&v).2, "Kahleeya holds the baton");
        assert_eq!(wait_of(&v).3, "You: 2/5 zones.");
        let mut i = info("waiting", true, Some(0));
        i.zone_name = Some("  ".to_string());
        let v = build(&i, RelayRole::Waiting, "p1", None, Some(0), Some("F8"));
        assert_eq!(wait_of(&v).3, "Hold F8 to take the baton.");
    }

    #[test]
    fn a_member_without_a_fresh_save_reads_its_reason() {
        let mut i = info("holder", true, None);
        member(&mut i, "p3").validated = false;
        let v = build(&i, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        let row = v.rows.iter().find(|r| r.participant_id == "p3").unwrap();
        assert_eq!(
            (row.right.as_str(), row.available),
            ("no fresh save", false)
        );

        let mut i = info("waiting", true, Some(0));
        member(&mut i, "p1").validated = false;
        let v = build(&i, RelayRole::Waiting, "p1", LAYER, Some(0), Some("F8"));
        let (_, _, _, detail, bar) = wait_of(&v);
        assert_eq!(
            (detail, bar),
            ("No fresh save: you cannot take the baton.", false)
        );
        assert_eq!(v.baton_hint, "");
    }

    #[test]
    fn members_who_are_out_and_the_runner_are_not_listed() {
        let mut i = info("holder", true, None);
        member(&mut i, "p3").status = ParticipantStatus::Disqualified;
        member(&mut i, "p4").status = ParticipantStatus::Finished;
        let v = build(&i, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        let names: Vec<_> = v.rows.iter().map(|r| r.name.as_str()).collect();
        assert_eq!(names, ["Roger", "Linlin_Tv"]);
    }

    #[test]
    fn an_empty_menu_says_why() {
        // Nobody eligible.
        let mut i = info("holder", true, None);
        for id in ["p1", "p3", "p4"] {
            member(&mut i, id).online = false;
        }
        let v = build(&i, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        assert!(v.rows.iter().all(|r| !r.available) && !v.rows.is_empty());
        assert_eq!(v.menu_note, "Nobody can take the baton right now");
        assert_eq!(v.menu_hint, "closes by itself after 5 s");
        // A team of one.
        let mut solo = info("holder", true, None);
        solo.members.retain(|m| m.participant_id == "p2");
        let v = build(&solo, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        assert!(v.rows.is_empty());
        assert_eq!(v.menu_note, "No teammate can take the baton");
        assert_eq!(v.menu_hint, "closes by itself after 5 s");
        // Somebody eligible: no note.
        let v = build(
            &info("holder", true, None),
            RelayRole::Holder,
            "p2",
            LAYER,
            None,
            Some("F8"),
        );
        assert_eq!(v.menu_note, "");
    }

    #[test]
    fn an_unknown_role_or_status_offers_nothing() {
        let v = build(
            &info("waiting", true, Some(0)),
            RelayRole::Unknown,
            "p1",
            LAYER,
            Some(0),
            Some("F8"),
        );
        assert_eq!(v, RelayView::default());
        let mut i = info("holder", true, None);
        member(&mut i, "p3").status = ParticipantStatus::Unknown;
        let v = build(&i, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        let row = v.rows.iter().find(|r| r.participant_id == "p3").unwrap();
        assert!(!row.available);
        assert_eq!(row.right, "status unknown");
    }

    #[test]
    fn a_capped_holder_reads_the_raw_count() {
        let mut i = info("holder", true, None);
        member(&mut i, "p2").zones = 6;
        i.gates_locked = true;
        let v = build(&i, RelayRole::Holder, "p2", LAYER, None, Some("F8"));
        assert_eq!(v.baton_count, "6/5 zones");
    }

    #[test]
    fn a_missing_name_or_layer_never_shows_as_empty() {
        let mut i = info("waiting", true, None);
        member(&mut i, "p2").name = String::new();
        let v = build(
            &i,
            RelayRole::Waiting,
            "p1",
            Some((-1, 0)),
            None,
            Some("F8"),
        );
        let (_, _, line, detail, _) = wait_of(&v);
        assert_eq!(line, "A teammate is in Leyndell, Royal Capital");
        assert_eq!(detail, "You: 2/5 zones.");
        assert_eq!(v.baton_who, "A teammate");
        i.holder_id = Some("ghost".to_string());
        i.holder_online = false;
        i.baton_free_in_s = Some(30);
        let v = build(&i, RelayRole::Waiting, "p1", None, Some(30), Some("F8"));
        assert_eq!(wait_of(&v).1, "THE HOLDER IS OFFLINE");
        // Holder offline with no countdown known.
        i.baton_free_in_s = None;
        let v = build(&i, RelayRole::Waiting, "p1", None, None, Some("F8"));
        assert_eq!(wait_of(&v).2, "The holder is not in the game");
        // Nobody named, baton not free.
        i.holder_id = None;
        let v = build(&i, RelayRole::Waiting, "p1", None, None, Some("F8"));
        assert_eq!(wait_of(&v).2, "Nobody holds the baton");
        assert_eq!(v.baton_who, "nobody");
    }

    #[test]
    fn no_string_carries_a_banned_separator() {
        let mut views = Vec::new();
        for (role, online, free_in) in [
            ("waiting", true, None),
            ("waiting", false, Some(30)),
            ("waiting", false, Some(0)),
            ("waiting", true, Some(0)),
            ("holder", true, None),
        ] {
            let r = if role == "holder" {
                RelayRole::Holder
            } else {
                RelayRole::Waiting
            };
            views.push(build(
                &info(role, online, free_in),
                r,
                "p1",
                LAYER,
                free_in,
                Some("F8"),
            ));
        }
        for v in views {
            let mut all = vec![
                v.baton_who,
                v.baton_count,
                v.baton_hint,
                v.menu_hint,
                v.menu_note,
            ];
            all.extend(v.rows.into_iter().flat_map(|r| [r.name, r.right]));
            if let Some(w) = v.wait {
                all.extend([w.title, w.line, w.detail]);
            }
            for s in all {
                assert!(!s.contains('\u{2014}') && !s.contains('\u{b7}'), "{s}");
                assert!(
                    !s.contains("null") && !s.contains("None") && !s.contains("--"),
                    "{s}"
                );
            }
        }
    }

    #[test]
    fn an_unbound_key_names_no_key_and_says_what_to_do() {
        let texts = |v: &RelayView| {
            let mut all = vec![
                v.baton_who.clone(),
                v.baton_count.clone(),
                v.baton_hint.clone(),
                v.menu_hint.clone(),
                v.menu_note.clone(),
            ];
            if let Some(w) = &v.wait {
                all.extend([w.title.clone(), w.line.clone(), w.detail.clone()]);
            }
            all
        };
        let free = build(
            &info("waiting", false, Some(0)),
            RelayRole::Waiting,
            "p1",
            LAYER,
            Some(0),
            None,
        );
        let holder = build(
            &info("holder", true, None),
            RelayRole::Holder,
            "p2",
            LAYER,
            None,
            None,
        );
        for v in [&free, &holder] {
            assert!(texts(v).iter().all(|t| !t.contains("F8")), "{:?}", texts(v));
            assert_eq!(v.baton_hint, "");
        }
        let wait = free.wait.as_ref().unwrap();
        assert_eq!(wait.detail, UNBOUND_TEXT);
        assert!(!wait.hold_bar);
        assert_eq!(holder.menu_hint, UNBOUND_TEXT);
    }

    #[test]
    fn a_rebound_key_is_named_in_every_hint() {
        let free = build(
            &info("waiting", false, Some(0)),
            RelayRole::Waiting,
            "p1",
            LAYER,
            Some(0),
            Some("G"),
        );
        let holder = build(
            &info("holder", true, None),
            RelayRole::Holder,
            "p2",
            LAYER,
            None,
            Some("G"),
        );
        assert_eq!(free.baton_hint, "G take");
        assert!(free.wait.as_ref().unwrap().detail.starts_with("Hold G "));
        assert_eq!(holder.baton_hint, "G pass");
        assert!(holder.menu_hint.starts_with("G next   hold G to pass"));
        assert!(!format!("{free:?}{holder:?}").contains("F8"));
    }

    #[test]
    fn the_pulse_stays_visible_and_peaks_at_each_period() {
        let period = PULSE_PERIOD.as_secs_f32();
        assert!((pulse_alpha(Duration::ZERO) - 1.0).abs() < 1e-4);
        assert!((pulse_alpha(PULSE_PERIOD) - 1.0).abs() < 1e-4);
        assert!((pulse_alpha(PULSE_PERIOD / 2) - PULSE_MIN).abs() < 1e-4);
        for step in 0..=200 {
            let alpha = pulse_alpha(Duration::from_secs_f32(period * 2.0 * step as f32 / 200.0));
            assert!(
                (PULSE_MIN - 1e-4..=1.0 + 1e-4).contains(&alpha),
                "{step}: {alpha}"
            );
        }
    }
}
