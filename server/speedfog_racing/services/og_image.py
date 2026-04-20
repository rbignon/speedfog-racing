"""OG image rendering pipeline: Jinja SVG templates → PNG bytes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["svg", "xml"]),
)

_TEMPLATE_BY_STATUS = {
    "setup": "og/setup.svg.j2",
    "running": "og/running.svg.j2",
    "finished": "og/finished.svg.j2",
}


def render_svg(status: str, ctx: dict[str, Any]) -> str:
    """Render the OG SVG for a given race status."""
    name = _TEMPLATE_BY_STATUS[status]
    template = _env.get_template(name)
    return template.render(**ctx)
