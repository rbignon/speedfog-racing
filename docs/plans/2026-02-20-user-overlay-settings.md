# User Overlay Settings

Date: 2026-02-20

## Problem

The mod's `font_size` is hardcoded at 32.0, which is too large for most players. Users need to configure this value per-account so it applies to all future seed packs.

## Design

### DB: JSON column on User

```python
overlay_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- `None` = all server defaults apply
- Partial dict (e.g. `{"font_size": 22.0}`) merged with server defaults
- Extensible for future settings (opacity, colors) without migration

### Server defaults

```python
OVERLAY_DEFAULTS = {"font_size": 18.0}
```

Default changes from 32.0 to 18.0. Mod's Rust default also updated for consistency.

### Validation (Pydantic)

```python
class OverlaySettings(BaseModel):
    font_size: float | None = None  # 8.0 - 72.0
```

Bounds: 8.0–72.0. Only non-None fields are stored.

### API

- `PATCH /users/me/settings` — accepts `OverlaySettings`, merges with existing, saves
- `GET /users/me` — includes `overlay_settings` in response

### Seed pack generation

`generate_player_config()` reads `participant.user.overlay_settings` and merges with `OVERLAY_DEFAULTS` to produce the TOML `font_size` value. Same for training config.

### Settings page

Reorganize `/settings` into sections:

- **Language** (existing)
- **Overlay** (new) — numeric input for font_size (8–72, default 18)

### Mod default

`config.rs`: `default_font_size()` changes from 32.0 to 18.0.
