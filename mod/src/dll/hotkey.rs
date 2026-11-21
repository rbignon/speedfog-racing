//! Hotkey handling - keyboard shortcuts for SpeedFog Racing
//!
//! Keys are read from ImGui's input state (fed by hudhook's WndProc hook),
//! so edge detection is reliable and hotkeys are inert when the game window
//! does not have focus.

use crate::core::key_names::{key_to_name, name_to_key, KeyCode};
use hudhook::imgui::{Key, Ui};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use windows::Win32::System::Threading::GetCurrentProcessId;
use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};

/// The ImGui key of a core key code.
fn imgui_key(code: KeyCode) -> Key {
    match code {
        KeyCode::F1 => Key::F1,
        KeyCode::F2 => Key::F2,
        KeyCode::F3 => Key::F3,
        KeyCode::F4 => Key::F4,
        KeyCode::F5 => Key::F5,
        KeyCode::F6 => Key::F6,
        KeyCode::F7 => Key::F7,
        KeyCode::F8 => Key::F8,
        KeyCode::F9 => Key::F9,
        KeyCode::F10 => Key::F10,
        KeyCode::F11 => Key::F11,
        KeyCode::F12 => Key::F12,
        KeyCode::A => Key::A,
        KeyCode::B => Key::B,
        KeyCode::C => Key::C,
        KeyCode::D => Key::D,
        KeyCode::E => Key::E,
        KeyCode::F => Key::F,
        KeyCode::G => Key::G,
        KeyCode::H => Key::H,
        KeyCode::I => Key::I,
        KeyCode::J => Key::J,
        KeyCode::K => Key::K,
        KeyCode::L => Key::L,
        KeyCode::M => Key::M,
        KeyCode::N => Key::N,
        KeyCode::O => Key::O,
        KeyCode::P => Key::P,
        KeyCode::Q => Key::Q,
        KeyCode::R => Key::R,
        KeyCode::S => Key::S,
        KeyCode::T => Key::T,
        KeyCode::U => Key::U,
        KeyCode::V => Key::V,
        KeyCode::W => Key::W,
        KeyCode::X => Key::X,
        KeyCode::Y => Key::Y,
        KeyCode::Z => Key::Z,
        KeyCode::Alpha0 => Key::Alpha0,
        KeyCode::Alpha1 => Key::Alpha1,
        KeyCode::Alpha2 => Key::Alpha2,
        KeyCode::Alpha3 => Key::Alpha3,
        KeyCode::Alpha4 => Key::Alpha4,
        KeyCode::Alpha5 => Key::Alpha5,
        KeyCode::Alpha6 => Key::Alpha6,
        KeyCode::Alpha7 => Key::Alpha7,
        KeyCode::Alpha8 => Key::Alpha8,
        KeyCode::Alpha9 => Key::Alpha9,
        KeyCode::Escape => Key::Escape,
        KeyCode::Space => Key::Space,
        KeyCode::Enter => Key::Enter,
        KeyCode::Tab => Key::Tab,
        KeyCode::Insert => Key::Insert,
        KeyCode::Delete => Key::Delete,
        KeyCode::Home => Key::Home,
        KeyCode::End => Key::End,
        KeyCode::PageUp => Key::PageUp,
        KeyCode::PageDown => Key::PageDown,
    }
}

/// A simple hotkey (single key, no modifiers)
#[derive(Debug, Clone, Copy)]
pub struct Hotkey {
    pub key: KeyCode,
}

impl Hotkey {
    /// Create a hotkey from a key name (e.g., "f9")
    pub fn from_name(name: &str) -> Option<Self> {
        name_to_key(name).map(|key| Hotkey { key })
    }

    /// Check if this hotkey was just pressed this frame
    pub fn is_just_pressed(&self, ui: &Ui) -> bool {
        ui.is_key_pressed_no_repeat(imgui_key(self.key))
    }

    /// The key's level: held down now, in the game's window; and whether the
    /// press in progress is cancelled this frame. ImGui only learns of a
    /// release through the game's own window messages, so a key released
    /// while another window had the focus would read down for good: the level
    /// drops as soon as the game is not the foreground window, that frame
    /// reads as a cancel (the press was cut short, not released), and `stale`
    /// keeps the level down until ImGui reports the key up, so returning to
    /// the game with the key already released cannot read as a hold. The
    /// foreground check runs only while the key reads down.
    pub fn read_level(&self, ui: &Ui, stale: &mut bool) -> (bool, bool) {
        if !ui.is_key_down(imgui_key(self.key)) {
            *stale = false;
            return (false, false);
        }
        if *stale {
            return (false, false);
        }
        if !game_has_focus() {
            *stale = true;
            return (false, true);
        }
        (true, false)
    }

    /// The key's name in upper case ("F8"), as the overlay's hints write it.
    pub fn label(&self) -> String {
        key_to_name(self.key).to_uppercase()
    }
}

/// The foreground window belongs to this process.
fn game_has_focus() -> bool {
    let mut pid = 0u32;
    // SAFETY: plain queries; a null foreground window gives pid 0.
    unsafe {
        let hwnd = GetForegroundWindow();
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        pid != 0 && pid == GetCurrentProcessId()
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
        Hotkey { key: KeyCode::F9 }
    }
}
