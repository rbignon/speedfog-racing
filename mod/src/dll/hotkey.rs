//! Hotkey handling - keyboard shortcuts for SpeedFog Racing

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::cell::RefCell;
use std::collections::HashMap;
use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;

// =============================================================================
// KEY STATE CACHE
// =============================================================================

thread_local! {
    static KEY_STATE_CACHE: RefCell<KeyStateCache> = RefCell::new(KeyStateCache::new());
}

struct KeyStateCache {
    states: HashMap<i32, (bool, bool)>,
    frame: u64,
}

impl KeyStateCache {
    fn new() -> Self {
        Self {
            states: HashMap::new(),
            frame: 0,
        }
    }

    fn new_frame(&mut self) {
        self.frame += 1;
        self.states.clear();
    }

    fn get_key_state(&mut self, key_code: i32) -> (bool, bool) {
        *self.states.entry(key_code).or_insert_with(|| {
            let state = unsafe { GetAsyncKeyState(key_code) } as u16;
            let just_pressed = (state & 1) != 0;
            let is_held = (state & 0x8000) != 0;
            (just_pressed, is_held)
        })
    }
}

/// Call this once per frame before checking any hotkeys
pub fn begin_hotkey_frame() {
    KEY_STATE_CACHE.with(|cache| {
        cache.borrow_mut().new_frame();
    });
}

fn get_cached_key_state(key_code: i32) -> (bool, bool) {
    KEY_STATE_CACHE.with(|cache| cache.borrow_mut().get_key_state(key_code))
}

// =============================================================================
// KEY CODE MAPPING
// =============================================================================

const KEY_MAPPINGS: &[(&str, i32)] = &[
    // Function keys (most common for hotkeys)
    ("f1", 0x70),
    ("f2", 0x71),
    ("f3", 0x72),
    ("f4", 0x73),
    ("f5", 0x74),
    ("f6", 0x75),
    ("f7", 0x76),
    ("f8", 0x77),
    ("f9", 0x78),
    ("f10", 0x79),
    ("f11", 0x7A),
    ("f12", 0x7B),
    // Letters
    ("a", 0x41),
    ("b", 0x42),
    ("c", 0x43),
    ("d", 0x44),
    ("e", 0x45),
    ("f", 0x46),
    ("g", 0x47),
    ("h", 0x48),
    ("i", 0x49),
    ("j", 0x4A),
    ("k", 0x4B),
    ("l", 0x4C),
    ("m", 0x4D),
    ("n", 0x4E),
    ("o", 0x4F),
    ("p", 0x50),
    ("q", 0x51),
    ("r", 0x52),
    ("s", 0x53),
    ("t", 0x54),
    ("u", 0x55),
    ("v", 0x56),
    ("w", 0x57),
    ("x", 0x58),
    ("y", 0x59),
    ("z", 0x5A),
    // Numbers
    ("0", 0x30),
    ("1", 0x31),
    ("2", 0x32),
    ("3", 0x33),
    ("4", 0x34),
    ("5", 0x35),
    ("6", 0x36),
    ("7", 0x37),
    ("8", 0x38),
    ("9", 0x39),
    // Special keys
    ("escape", 0x1B),
    ("esc", 0x1B),
    ("space", 0x20),
    ("enter", 0x0D),
    ("tab", 0x09),
    ("insert", 0x2D),
    ("delete", 0x2E),
    ("home", 0x24),
    ("end", 0x23),
    ("pageup", 0x21),
    ("pagedown", 0x22),
];

fn name_to_keycode(name: &str) -> Option<i32> {
    let name_lower = name.to_lowercase();
    KEY_MAPPINGS
        .iter()
        .find(|(n, _)| *n == name_lower)
        .map(|(_, code)| *code)
}

fn keycode_to_name(code: i32) -> &'static str {
    match code {
        // Function keys
        0x70 => "F1",
        0x71 => "F2",
        0x72 => "F3",
        0x73 => "F4",
        0x74 => "F5",
        0x75 => "F6",
        0x76 => "F7",
        0x77 => "F8",
        0x78 => "F9",
        0x79 => "F10",
        0x7A => "F11",
        0x7B => "F12",
        // Letters A-Z
        0x41 => "A",
        0x42 => "B",
        0x43 => "C",
        0x44 => "D",
        0x45 => "E",
        0x46 => "F",
        0x47 => "G",
        0x48 => "H",
        0x49 => "I",
        0x4A => "J",
        0x4B => "K",
        0x4C => "L",
        0x4D => "M",
        0x4E => "N",
        0x4F => "O",
        0x50 => "P",
        0x51 => "Q",
        0x52 => "R",
        0x53 => "S",
        0x54 => "T",
        0x55 => "U",
        0x56 => "V",
        0x57 => "W",
        0x58 => "X",
        0x59 => "Y",
        0x5A => "Z",
        // Numbers 0-9
        0x30 => "0",
        0x31 => "1",
        0x32 => "2",
        0x33 => "3",
        0x34 => "4",
        0x35 => "5",
        0x36 => "6",
        0x37 => "7",
        0x38 => "8",
        0x39 => "9",
        // Special keys
        0x1B => "Escape",
        0x20 => "Space",
        0x0D => "Enter",
        0x09 => "Tab",
        0x2D => "Insert",
        0x2E => "Delete",
        0x24 => "Home",
        0x23 => "End",
        0x21 => "PageUp",
        0x22 => "PageDown",
        _ => "Unknown",
    }
}

// =============================================================================
// HOTKEY TYPE
// =============================================================================

/// A simple hotkey (single key, no modifiers for Phase 1)
#[derive(Debug, Clone, Copy)]
pub struct Hotkey {
    pub key: i32,
}

impl Hotkey {
    /// Create a hotkey from a key name (e.g., "f9")
    pub fn from_name(name: &str) -> Option<Self> {
        name_to_keycode(name).map(|key| Hotkey { key })
    }

    /// Check if this hotkey was just pressed
    pub fn is_just_pressed(&self) -> bool {
        let (just_pressed, _) = get_cached_key_state(self.key);
        just_pressed
    }
}

impl Serialize for Hotkey {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&keycode_to_name(self.key).to_lowercase())
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

impl Default for Hotkey {
    fn default() -> Self {
        Hotkey { key: 0x78 } // F9
    }
}
