//! Death icon texture for the overlay

use hudhook::imgui::TextureId;
use hudhook::RenderContext;
use tracing::{debug, info};

const DEATH_PNG: &[u8] = include_bytes!("../../assets/death.png");

/// Single-icon texture loaded from an embedded PNG.
pub struct DeathIcon {
    texture_id: TextureId,
}

impl DeathIcon {
    /// Decode the embedded PNG and upload as a GPU texture.
    pub fn load(render_context: &mut dyn RenderContext) -> Result<Self, String> {
        info!("Loading death icon texture");

        use image::ImageReader;
        use std::io::Cursor;

        let img = ImageReader::new(Cursor::new(DEATH_PNG))
            .with_guessed_format()
            .map_err(|e| format!("Failed to guess format: {}", e))?
            .decode()
            .map_err(|e| format!("Failed to decode death icon PNG: {}", e))?;

        let rgba = img.to_rgba8();
        let (width, height) = rgba.dimensions();
        let raw_data = rgba.into_raw();

        debug!(
            width,
            height,
            bytes = raw_data.len(),
            "Decoded death icon PNG"
        );

        let texture_id = render_context
            .load_texture(&raw_data, width, height)
            .map_err(|e| format!("Failed to load death icon texture: {:?}", e))?;

        Ok(Self { texture_id })
    }

    pub fn texture_id(&self) -> TextureId {
        self.texture_id
    }
}
