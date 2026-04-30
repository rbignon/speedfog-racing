"""Static catalog dataclasses (configuration types, not ORM)."""

from dataclasses import dataclass
from typing import Literal

BadgeLifecycle = Literal["permanent", "transient"]


@dataclass(frozen=True)
class Badge:
    id: str
    name: str
    description: str
    icon_filename: str
    lifecycle: BadgeLifecycle
    sort_order: int = 0


@dataclass(frozen=True)
class NameTemplate:
    id: str
    name: str
    description: str
    color: str | None = None
    gradient: tuple[str, str] | None = None
    background_css: str | None = None
    sort_order: int = 0
