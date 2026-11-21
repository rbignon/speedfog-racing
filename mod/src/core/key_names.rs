//! The keys the config accepts for a hotkey, by name. Pure: the Windows
//! shell maps a `KeyCode` to ImGui's key (`dll/hotkey.rs`).

/// A key a hotkey may be bound to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyCode {
    F1,
    F2,
    F3,
    F4,
    F5,
    F6,
    F7,
    F8,
    F9,
    F10,
    F11,
    F12,
    A,
    B,
    C,
    D,
    E,
    F,
    G,
    H,
    I,
    J,
    K,
    L,
    M,
    N,
    O,
    P,
    Q,
    R,
    S,
    T,
    U,
    V,
    W,
    X,
    Y,
    Z,
    Alpha0,
    Alpha1,
    Alpha2,
    Alpha3,
    Alpha4,
    Alpha5,
    Alpha6,
    Alpha7,
    Alpha8,
    Alpha9,
    Escape,
    Space,
    Enter,
    Tab,
    Insert,
    Delete,
    Home,
    End,
    PageUp,
    PageDown,
}

/// Key name <-> key code, used for both parsing and serialization. When
/// several names map to the same key ("escape"/"esc"), the first entry is
/// the canonical name used when serializing.
const KEY_MAPPINGS: &[(&str, KeyCode)] = &[
    ("f1", KeyCode::F1),
    ("f2", KeyCode::F2),
    ("f3", KeyCode::F3),
    ("f4", KeyCode::F4),
    ("f5", KeyCode::F5),
    ("f6", KeyCode::F6),
    ("f7", KeyCode::F7),
    ("f8", KeyCode::F8),
    ("f9", KeyCode::F9),
    ("f10", KeyCode::F10),
    ("f11", KeyCode::F11),
    ("f12", KeyCode::F12),
    ("a", KeyCode::A),
    ("b", KeyCode::B),
    ("c", KeyCode::C),
    ("d", KeyCode::D),
    ("e", KeyCode::E),
    ("f", KeyCode::F),
    ("g", KeyCode::G),
    ("h", KeyCode::H),
    ("i", KeyCode::I),
    ("j", KeyCode::J),
    ("k", KeyCode::K),
    ("l", KeyCode::L),
    ("m", KeyCode::M),
    ("n", KeyCode::N),
    ("o", KeyCode::O),
    ("p", KeyCode::P),
    ("q", KeyCode::Q),
    ("r", KeyCode::R),
    ("s", KeyCode::S),
    ("t", KeyCode::T),
    ("u", KeyCode::U),
    ("v", KeyCode::V),
    ("w", KeyCode::W),
    ("x", KeyCode::X),
    ("y", KeyCode::Y),
    ("z", KeyCode::Z),
    ("0", KeyCode::Alpha0),
    ("1", KeyCode::Alpha1),
    ("2", KeyCode::Alpha2),
    ("3", KeyCode::Alpha3),
    ("4", KeyCode::Alpha4),
    ("5", KeyCode::Alpha5),
    ("6", KeyCode::Alpha6),
    ("7", KeyCode::Alpha7),
    ("8", KeyCode::Alpha8),
    ("9", KeyCode::Alpha9),
    ("escape", KeyCode::Escape),
    ("esc", KeyCode::Escape),
    ("space", KeyCode::Space),
    ("enter", KeyCode::Enter),
    ("tab", KeyCode::Tab),
    ("insert", KeyCode::Insert),
    ("delete", KeyCode::Delete),
    ("home", KeyCode::Home),
    ("end", KeyCode::End),
    ("pageup", KeyCode::PageUp),
    ("pagedown", KeyCode::PageDown),
];

/// The key a config name stands for, case-insensitively.
pub fn name_to_key(name: &str) -> Option<KeyCode> {
    let name_lower = name.to_lowercase();
    KEY_MAPPINGS
        .iter()
        .find(|(n, _)| *n == name_lower)
        .map(|(_, key)| *key)
}

/// The canonical name of a key.
pub fn key_to_name(key: KeyCode) -> &'static str {
    KEY_MAPPINGS
        .iter()
        .find(|(_, k)| *k == key)
        .map(|(name, _)| *name)
        .unwrap_or("unknown")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_accepted_name_reaches_its_canonical_name() {
        for (name, key) in KEY_MAPPINGS {
            assert_eq!(name_to_key(name), Some(*key), "{name}");
            let canonical = key_to_name(*key);
            // The canonical name parses back to the same key, and an alias
            // maps to the first name listed for its key.
            assert_eq!(name_to_key(canonical), Some(*key), "{name}");
            let first = KEY_MAPPINGS.iter().find(|(_, k)| k == key).unwrap().0;
            assert_eq!(canonical, first);
        }
        assert_eq!(key_to_name(name_to_key("esc").unwrap()), "escape");
        assert_eq!(key_to_name(name_to_key("F8").unwrap()), "f8");
    }

    #[test]
    fn a_name_is_listed_once_and_an_unknown_one_is_none() {
        for (i, (name, _)) in KEY_MAPPINGS.iter().enumerate() {
            assert!(
                KEY_MAPPINGS[i + 1..].iter().all(|(n, _)| n != name),
                "{name}"
            );
        }
        assert_eq!(name_to_key("f13"), None);
        assert_eq!(name_to_key(""), None);
    }

    #[test]
    fn every_key_has_a_name() {
        // A variant with no table row would serialize as "unknown".
        for (_, key) in KEY_MAPPINGS {
            assert_ne!(key_to_name(*key), "unknown");
        }
    }
}
