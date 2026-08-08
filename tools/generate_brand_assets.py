#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["fonttools>=4.53", "brotli", "resvg-py"]
# ///
"""Regenerate the static brand assets and the server-side OG fonts.

Letterforms come from the self-hosted woff2 faces in web/static/fonts/ and are
outlined to SVG paths, so the emitted SVGs render identically without any font
installed (an SVG favicon has no webfont access at all).

Outputs:
- web/static/favicon.svg + favicon-{48,96,192}.png  (SF monogram)
- web/static/og-image.svg + og-image.png            (wordmark share card)
- server/speedfog_racing/static/fonts/*.ttf         (resvg needs real font
  files to rasterize the dynamic per-race/per-daily OG templates)
"""

from __future__ import annotations

from pathlib import Path

import resvg_py
from fontTools.misc.transform import Transform
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
WEB_FONTS = ROOT / "web" / "static" / "fonts"
WEB_STATIC = ROOT / "web" / "static"
SERVER_FONTS = ROOT / "server" / "speedfog_racing" / "static" / "fonts"

BG = "#0f1923"
TEXT = "#e8e6e1"
BRASS = "#c8a44e"
GREY = "#96a0ad"

TAGLINE = "Competitive Elden Ring racing through randomized fog gates"


def text_to_path(
    font_path: Path, text: str, size: float, letter_spacing: float = 0.0
) -> tuple[str, float]:
    """Lay out ``text`` at ``size`` px; return (svg path data, advance width).

    The path is baseline-relative: y=0 is the baseline, y grows downward.
    Plain advance widths, no kerning: fine for short display strings.
    The width excludes the trailing letter-spacing, so concatenated runs
    should be placed at ``x + width + letter_spacing``.
    """
    font = TTFont(str(font_path))
    upem = font["head"].unitsPerEm
    scale = size / upem
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    hmtx = font["hmtx"]
    x = 0.0
    commands: list[str] = []
    for ch in text:
        gname = cmap[ord(ch)]
        pen = SVGPathPen(glyph_set)
        glyph_set[gname].draw(TransformPen(pen, Transform(scale, 0, 0, -scale, x, 0)))
        d = pen.getCommands()
        if d:
            commands.append(d)
        x += hmtx[gname][0] * scale + letter_spacing
    return " ".join(commands), x - (letter_spacing if text else 0.0)


def char_advance(font_path: Path, ch: str, size: float) -> float:
    font = TTFont(str(font_path))
    upem = font["head"].unitsPerEm
    return font["hmtx"][font.getBestCmap()[ord(ch)]][0] * size / upem


def build_favicon() -> str:
    cond700 = WEB_FONTS / "barlow-condensed-700-latin.woff2"
    size, spacing, baseline = 336.0, 8.0, 376.0
    d_s, w_s = text_to_path(cond700, "S", size)
    d_f, w_f = text_to_path(cond700, "F", size)
    total = w_s + spacing + w_f
    # +8: optical centering nudge (the F is right-light), validated in mockup
    x0 = (512 - total) / 2 + 8
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <rect width="512" height="512" rx="112" fill="{BG}"/>
  <path transform="translate({x0:.1f} {baseline:.0f})" fill="{TEXT}" d="{d_s}"/>
  <path transform="translate({x0 + w_s + spacing:.1f} {baseline:.0f})" fill="{BRASS}" d="{d_f}"/>
</svg>
"""


def build_og_image() -> str:
    cond700 = WEB_FONTS / "barlow-condensed-700-latin.woff2"
    cond600 = WEB_FONTS / "barlow-condensed-600-latin.woff2"
    barlow400 = WEB_FONTS / "barlow-400-latin.woff2"
    wm_size, wm_spacing = 126.0, 5.0
    d1, w1 = text_to_path(cond700, "SPEEDFOG", wm_size, wm_spacing)
    d2, w2 = text_to_path(cond600, "RACING", wm_size, wm_spacing)
    gap = char_advance(cond700, " ", wm_size) + 2 * wm_spacing
    total = w1 + gap + w2
    x0 = (1200 - total) / 2
    d_t, w_t = text_to_path(barlow400, TAGLINE, 30.0)
    x_t = (1200 - w_t) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
  <rect width="1200" height="630" fill="{BG}"/>
  <path transform="translate({x0:.1f} 330)" fill="{TEXT}" d="{d1}"/>
  <path transform="translate({x0 + w1 + gap:.1f} 330)" fill="{BRASS}" d="{d2}"/>
  <polygon points="375,368 375,384 389,376" fill="{BRASS}"/>
  <line x1="389" y1="376" x2="591" y2="376" stroke="{BRASS}" stroke-width="3"/>
  <circle cx="600" cy="376" r="7" fill="{BG}" stroke="{BRASS}" stroke-width="3"/>
  <line x1="609" y1="376" x2="811" y2="376" stroke="{BRASS}" stroke-width="3"/>
  <rect x="811" y="369" width="14" height="14" fill="{BRASS}"/>
  <path transform="translate({x_t:.1f} 446)" fill="{GREY}" d="{d_t}"/>
</svg>
"""


def rasterize(
    svg: str, dest: Path, width: int | None = None, height: int | None = None
) -> None:
    png = bytes(
        resvg_py.svg_to_bytes(
            svg_string=svg, width=width, height=height, skip_system_fonts=True
        )
    )
    dest.write_bytes(png)


STATIC_FACES = [
    "barlow-condensed-600-latin",
    "barlow-condensed-600-latin-ext",
    "barlow-condensed-700-latin",
    "barlow-condensed-700-latin-ext",
    "barlow-400-latin",
    "barlow-400-latin-ext",
]
MONO_WEIGHTS = [400, 500, 600]


def _family_for_stem(stem: str) -> str:
    """Derive the canonical family name resvg should key a face under."""
    if stem.startswith("barlow-condensed"):
        return "Barlow Condensed"
    if stem.startswith("barlow-"):
        return "Barlow"
    if stem.startswith("spline-sans-mono"):
        return "Spline Sans Mono"
    raise ValueError(f"unrecognized font stem: {stem!r}")


def _set_family_name(font: TTFont, family: str) -> None:
    """Normalize nameID 1 (family) and 16 (typographic family) to ``family``.

    Some Google Fonts static cuts (e.g. the Barlow Condensed SemiBold TTF)
    use legacy naming where nameID 1 embeds the weight ("Barlow Condensed
    SemiBold") and there is no nameID 16. resvg's fontdb groups faces by
    nameID 16 when present, else nameID 1, so a weight-suffixed nameID 1
    splits that weight into its own family and font-weight lookups against
    the shared family skip right past it. Pinning both IDs to the same
    family on every emitted face keeps all weights queryable together, with
    OS/2 usWeightClass doing the weight selection.
    """
    name_table = font["name"]
    for name_id in (1, 16):
        name_table.setName(family, name_id, 3, 1, 0x409)
        name_table.setName(family, name_id, 1, 0, 0)


def _break_subset_weight_tie(font: TTFont) -> None:
    """Nudge a latin-ext face's OS/2 weight off its latin sibling's value.

    Each weight in each family ships as two files (a latin subset and a
    latin-ext subset covering accented characters), both meant to register
    under the same family and weight so either can serve a glyph. But two
    faces tied on the exact same (family, weight, style, stretch) is
    exactly the condition where resvg's fontdb selection was found to be
    unreliable: an exact-weight query can spuriously fail to disambiguate
    between the tied pair and abandon the family match entirely, falling
    back to substituting glyphs from an unrelated loaded font. This was
    verified directly against resvg's fontdb output (not just by reading
    name tables back), and the failure was observed to depend on
    incidental byte-level differences (even an unrelated embedded
    timestamp) rather than any single font property, so the robust fix is
    to remove the exact tie altogether rather than tune flags and hope. A
    latin-ext face is never the only candidate for a plain-Latin query, so
    nudging its weight by 1 doesn't change which face serves normal text;
    it only stops the two files from being indistinguishable to fontdb's
    exact-match lookup.
    """
    font["OS/2"].usWeightClass += 1


def convert_server_fonts() -> None:
    SERVER_FONTS.mkdir(parents=True, exist_ok=True)
    for stem in STATIC_FACES:
        font = TTFont(str(WEB_FONTS / f"{stem}.woff2"))
        _set_family_name(font, _family_for_stem(stem))
        if stem.endswith("-ext"):
            _break_subset_weight_tie(font)
        font.flavor = None
        font.save(str(SERVER_FONTS / f"{stem}.ttf"))
    for subset in ("latin", "latin-ext"):
        for wght in MONO_WEIGHTS:
            font = TTFont(str(WEB_FONTS / f"spline-sans-mono-{subset}.woff2"))
            if "fvar" in font:
                instantiateVariableFont(
                    font, {"wght": wght}, inplace=True, updateFontNames=False
                )
            # resvg's fontdb matches by OS/2 weight; make the pin explicit
            font["OS/2"].usWeightClass = wght
            _set_family_name(font, "Spline Sans Mono")
            if subset == "latin-ext":
                _break_subset_weight_tie(font)
            font.flavor = None
            font.save(str(SERVER_FONTS / f"spline-sans-mono-{wght}-{subset}.ttf"))


def main() -> None:
    favicon = build_favicon()
    (WEB_STATIC / "favicon.svg").write_text(favicon)
    for px in (48, 96, 192):
        rasterize(favicon, WEB_STATIC / f"favicon-{px}.png", width=px, height=px)
    og = build_og_image()
    (WEB_STATIC / "og-image.svg").write_text(og)
    rasterize(og, WEB_STATIC / "og-image.png")
    convert_server_fonts()
    print("brand assets regenerated")


if __name__ == "__main__":
    main()
