//! Hotkey handling - keyboard shortcuts for SpeedFog Racing
//!
//! Keys are read from ImGui's input state (fed by hudhook's WndProc hook),
//! so edge detection is reliable and hotkeys are inert when the game window
//! does not have focus.

use hudhook::imgui::{Key, Ui};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// Key name <-> imgui key table, used for both parsing and serialization.
/// When several names map to the same key ("escape"/"esc"), the first entry
/// is the canonical name used when serializing.
const KEY_MAPPINGS: &[(&str, Key)] = &[
    // Function keys (most common for hotkeys)
    ("f1", Key::F1),
    ("f2", Key::F2),
    ("f3", Key::F3),
    ("f4", Key::F4),
    ("f5", Key::F5),
    ("f6", Key::F6),
    ("f7", Key::F7),
    ("f8", Key::F8),
    ("f9", Key::F9),
    ("f10", Key::F10),
    ("f11", Key::F11),
    ("f12", Key::F12),
    // Letters
    ("a", Key::A),
    ("b", Key::B),
    ("c", Key::C),
    ("d", Key::D),
    ("e", Key::E),
    ("f", Key::F),
    ("g", Key::G),
    ("h", Key::H),
    ("i", Key::I),
    ("j", Key::J),
    ("k", Key::K),
    ("l", Key::L),
    ("m", Key::M),
    ("n", Key::N),
    ("o", Key::O),
    ("p", Key::P),
    ("q", Key::Q),
    ("r", Key::R),
    ("s", Key::S),
    ("t", Key::T),
    ("u", Key::U),
    ("v", Key::V),
    ("w", Key::W),
    ("x", Key::X),
    ("y", Key::Y),
    ("z", Key::Z),
    // Numbers
    ("0", Key::Alpha0),
    ("1", Key::Alpha1),
    ("2", Key::Alpha2),
    ("3", Key::Alpha3),
    ("4", Key::Alpha4),
    ("5", Key::Alpha5),
    ("6", Key::Alpha6),
    ("7", Key::Alpha7),
    ("8", Key::Alpha8),
    ("9", Key::Alpha9),
    // Special keys
    ("escape", Key::Escape),
    ("esc", Key::Escape),
    ("space", Key::Space),
    ("enter", Key::Enter),
    ("tab", Key::Tab),
    ("insert", Key::Insert),
    ("delete", Key::Delete),
    ("home", Key::Home),
    ("end", Key::End),
    ("pageup", Key::PageUp),
    ("pagedown", Key::PageDown),
];

fn name_to_key(name: &str) -> Option<Key> {
    let name_lower = name.to_lowercase();
    KEY_MAPPINGS
        .iter()
        .find(|(n, _)| *n == name_lower)
        .map(|(_, key)| *key)
}

fn key_to_name(key: Key) -> &'static str {
    KEY_MAPPINGS
        .iter()
        .find(|(_, k)| *k == key)
        .map(|(name, _)| *name)
        .unwrap_or("unknown")
}

/// A simple hotkey (single key, no modifiers)
#[derive(Debug, Clone, Copy)]
pub struct Hotkey {
    pub key: Key,
}

impl Hotkey {
    /// Create a hotkey from a key name (e.g., "f9")
    pub fn from_name(name: &str) -> Option<Self> {
        name_to_key(name).map(|key| Hotkey { key })
    }

    /// Check if this hotkey was just pressed this frame
    pub fn is_just_pressed(&self, ui: &Ui) -> bool {
        ui.is_key_pressed_no_repeat(self.key)
    }
}

impl Serialize for Hotkey {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(key_to_name(self.key))
    }
}

impl<'de> Deserialize<'de> for Hotkey {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        Hotkey::from_name(&s)
            .ok_or_else(|| serde::de::Error::custom(format!("Unknown key name: '{}'", s)))
    }
}

/// Deserialize an optional hotkey: `"none"` or `""` means disabled (None).
pub fn deserialize_optional_hotkey<'de, D>(deserializer: D) -> Result<Option<Hotkey>, D::Error>
where
    D: Deserializer<'de>,
{
    let s = String::deserialize(deserializer)?;
    let trimmed = s.trim();
    if trimmed.is_empty() || trimmed.eq_ignore_ascii_case("none") {
        return Ok(None);
    }
    Hotkey::from_name(trimmed)
        .map(Some)
        .ok_or_else(|| serde::de::Error::custom(format!("Unknown key name: '{}'", s)))
}

/// Serialize an optional hotkey: None becomes "none".
pub fn serialize_optional_hotkey<S>(
    value: &Option<Hotkey>,
    serializer: S,
) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match value {
        Some(hotkey) => hotkey.serialize(serializer),
        None => serializer.serialize_str("none"),
    }
}

impl Default for Hotkey {
    fn default() -> Self {
        Hotkey { key: Key::F9 }
    }
}
