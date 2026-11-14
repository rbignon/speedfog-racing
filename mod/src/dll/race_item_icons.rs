//! Race item icon textures for the overlay

use std::collections::HashMap;

use hudhook::imgui::TextureId;
use hudhook::RenderContext;
use tracing::{debug, info, warn};

/// Icon name (the key of the server catalog's `icon`) and its embedded PNG.
/// The art is not in the repository: `uv run tools/fetch_race_item_icons.py`
/// downloads it (gitignored files) and must run before any build of the DLL.
const ICON_PNGS: &[(&str, &[u8])] = &[
    (
        "shield",
        include_bytes!("../../assets/race_items/shield.png"),
    ),
    (
        "rune_pouch",
        include_bytes!("../../assets/race_items/rune_pouch.png"),
    ),
    (
        "banana",
        include_bytes!("../../assets/race_items/banana.png"),
    ),
    (
        "red_shell",
        include_bytes!("../../assets/race_items/red_shell.png"),
    ),
    (
        "mushroom",
        include_bytes!("../../assets/race_items/mushroom.png"),
    ),
    (
        "hammer",
        include_bytes!("../../assets/race_items/hammer.png"),
    ),
    ("ink", include_bytes!("../../assets/race_items/ink.png")),
    (
        "blue_shell",
        include_bytes!("../../assets/race_items/blue_shell.png"),
    ),
    (
        "lightning",
        include_bytes!("../../assets/race_items/lightning.png"),
    ),
    (
        "flask_stopper",
        include_bytes!("../../assets/race_items/flask_stopper.png"),
    ),
    (
        "toxic_blossom",
        include_bytes!("../../assets/race_items/toxic_blossom.png"),
    ),
];
const UNKNOWN_PNG: &[u8] = include_bytes!("../../assets/race_items/unknown.png");

/// Every race item icon as a GPU texture, uploaded once at init.
pub struct RaceItemIcons {
    textures: HashMap<&'static str, TextureId>,
    unknown: TextureId,
}

fn upload(
    render_context: &mut dyn RenderContext,
    name: &str,
    png: &[u8],
) -> Result<TextureId, String> {
    use image::ImageReader;
    use std::io::Cursor;

    let img = ImageReader::new(Cursor::new(png))
        .with_guessed_format()
        .map_err(|e| format!("Failed to guess format of {}: {}", name, e))?
        .decode()
        .map_err(|e| format!("Failed to decode {}: {}", name, e))?;
    let rgba = img.to_rgba8();
    let (width, height) = rgba.dimensions();
    debug!(name, width, height, "Decoded race item icon");
    render_context
        .load_texture(&rgba.into_raw(), width, height)
        .map_err(|e| format!("Failed to load {} texture: {:?}", name, e))
}

impl RaceItemIcons {
    /// Decode and upload every icon. A catalog icon that fails to load falls
    /// back to the unknown one; the unknown icon failing fails the whole load.
    pub fn load(render_context: &mut dyn RenderContext) -> Result<Self, String> {
        info!("Loading race item icon textures");
        let unknown = upload(render_context, "unknown", UNKNOWN_PNG)?;
        let mut textures = HashMap::new();
        for (name, png) in ICON_PNGS {
            match upload(render_context, name, png) {
                Ok(id) => {
                    textures.insert(*name, id);
                }
                Err(e) => warn!(error = %e, "Race item icon skipped"),
            }
        }
        Ok(Self { textures, unknown })
    }

    /// The texture of an icon name, the unknown icon for any other name.
    pub fn texture(&self, icon: &str) -> TextureId {
        self.textures.get(icon).copied().unwrap_or(self.unknown)
    }
}
