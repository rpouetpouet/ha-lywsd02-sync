#!/usr/bin/env python3
"""Generate Home Assistant brand assets for the `lywsd02` custom integration.

Renders programmatically (Pillow only, no GPU / no diffusion model):
  - a pictogram of a Xiaomi LYWSD02 e-ink clock (rounded e-ink screen showing
    big digits + a small temperature/humidity line, on a light stand)
  - light + dark themes
  - icon.png 256x256, icon@2x.png 512x512, dark_icon(+@2x)
  - logo.png 1024x256, logo@2x.png 2048x512, dark_logo(+@2x)
    (pictogram + "LYWSD02 Sync" wordmark, DejaVu Sans Bold)

Everything is drawn at 4x the final size and downsampled with LANCZOS.

Usage:
    python3 tools/generate_brand_assets.py [--out DIR]

Deterministic: re-running produces byte-identical PNGs.
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPERSAMPLE = 4  # draw at 4x final size, then LANCZOS-downsample

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(REPO, "custom_components", "lywsd02", "brand")

# Bundled font (preferred) then common system fallbacks.
FONT_CANDIDATES = [
    os.path.join(HERE, "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

# --- Palette (spec) --------------------------------------------------------
SLATE = (44, 62, 80, 255)        # #2C3E50 dark slate
PAPER = (242, 243, 245, 255)     # #F2F3F5 off white
LIGHT = (232, 234, 237, 255)     # #E8EAED light grey
DARKSCREEN = (38, 50, 56, 255)   # #263238 dark screen
ACCENT = (3, 169, 244, 255)      # #03A9F4 HA blue

THEMES = {
    # body (frame/stand), screen, ink (digits on screen), wordmark, accent
    "light": {"body": SLATE, "screen": PAPER, "ink": SLATE, "word": SLATE,
              "accent": ACCENT},
    "dark": {"body": LIGHT, "screen": DARKSCREEN, "ink": LIGHT, "word": LIGHT,
             "accent": ACCENT},
}

# --- Pictogram geometry, normalised to the unit square [0..1] --------------
# (x0, y0, x1, y1, corner_radius)
BODY = (0.105, 0.130, 0.895, 0.790, 0.070)
SCREEN = (0.150, 0.175, 0.850, 0.745, 0.040)
NECK = (0.440, 0.790, 0.560, 0.838, 0.014)
BASE = (0.375, 0.838, 0.625, 0.884, 0.024)
STATUS_DOT = (0.795, 0.225, 0.017)  # cx, cy, r

TIME_TEXT = "07:30"
SUB_TEXT = "21.4\u00b0C  48%"


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _load_font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    print("WARNING: no TrueType font found, falling back to bitmap default",
          file=sys.stderr)
    return ImageFont.load_default(size)


def _text_size(draw: ImageDraw.ImageDraw, text: str,
               font: ImageFont.FreeTypeFont):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: float,
              start: int, min_size: int = 8):
    """Largest bold font size (<=start) that keeps `text` within max_w."""
    size = int(start)
    while size > min_size:
        font = _load_font(size)
        w, _ = _text_size(draw, text, font)
        if w <= max_w:
            return font
        size -= 2
    return _load_font(min_size)


def _centered_text(draw, cx, cy, text, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (l + r) / 2, cy - (t + b) / 2), text, font=font, fill=fill)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _rr(draw, ox, oy, side, box, fill):
    """Rounded rect from a normalised (x0,y0,x1,y1,r) tuple."""
    x0, y0, x1, y1, r = box
    x0, y0, x1, y1, r = x0 * side, y0 * side, x1 * side, y1 * side, r * side
    draw.rounded_rectangle([ox + x0, oy + y0, ox + x1, oy + y1],
                           radius=r, fill=fill)


def draw_pictogram(draw: ImageDraw.ImageDraw, ox: float, oy: float,
                   side: float, theme: dict) -> None:
    """Draw the e-ink clock pictogram in a `side`-sided square at (ox, oy)."""
    # Stand / neck / base first, then the body over it.
    _rr(draw, ox, oy, side, NECK, theme["body"])
    _rr(draw, ox, oy, side, BASE, theme["body"])
    _rr(draw, ox, oy, side, BODY, theme["body"])
    # e-ink screen
    _rr(draw, ox, oy, side, SCREEN, theme["screen"])

    sx0, sy0 = ox + SCREEN[0] * side, oy + SCREEN[1] * side
    sx1, sy1 = ox + SCREEN[2] * side, oy + SCREEN[3] * side
    sw = sx1 - sx0

    # big time
    time_font = _fit_font(draw, TIME_TEXT, 0.66 * sw, int(0.30 * side))
    _centered_text(draw, (sx0 + sx1) / 2, oy + 0.420 * side,
                   TIME_TEXT, time_font, theme["ink"])

    # small temp/humidity line
    sub_font = _fit_font(draw, SUB_TEXT, 0.72 * sw, int(0.13 * side))
    _centered_text(draw, (sx0 + sx1) / 2, oy + 0.615 * side,
                   SUB_TEXT, sub_font, theme["ink"])

    # HA blue status dot, top-right inside the screen
    dcx, dcy, dr = STATUS_DOT
    cx, cy, r = ox + dcx * side, oy + dcy * side, dr * side
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=theme["accent"])


def render_icon(w: int, h: int, theme: dict) -> Image.Image:
    img = Image.new("RGBA", (w * SUPERSAMPLE, h * SUPERSAMPLE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    side = min(w, h) * SUPERSAMPLE
    ox = (w * SUPERSAMPLE - side) / 2
    oy = (h * SUPERSAMPLE - side) / 2
    draw_pictogram(d, ox, oy, side, theme)
    return img.resize((w, h), Image.Resampling.LANCZOS)


def render_logo(w: int, h: int, theme: dict, wordmark: str) -> Image.Image:
    W, H = w * SUPERSAMPLE, h * SUPERSAMPLE
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    side = 0.92 * H
    ox = 0.035 * W
    oy = (H - side) / 2
    draw_pictogram(d, ox, oy, side, theme)

    text_x0 = ox + side + 0.030 * W
    text_max_w = W - text_x0 - 0.035 * W
    font = _fit_font(d, wordmark, text_max_w, int(0.52 * H))
    _centered_text(d, text_x0 + text_max_w / 2, H / 2,
                   wordmark, font, theme["word"])
    return img.resize((w, h), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def save(img: Image.Image, path: str) -> None:
    img.save(path, format="PNG", optimize=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--wordmark", default="LYWSD02 Sync")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    jobs = [
        ("icon.png",          (256, 256),  "light", "icon"),
        ("icon@2x.png",       (512, 512),  "light", "icon"),
        ("dark_icon.png",     (256, 256),  "dark",  "icon"),
        ("dark_icon@2x.png",  (512, 512),  "dark",  "icon"),
        ("logo.png",          (1024, 256), "light", "logo"),
        ("logo@2x.png",       (2048, 512), "light", "logo"),
        ("dark_logo.png",     (1024, 256), "dark",  "logo"),
        ("dark_logo@2x.png",  (2048, 512), "dark",  "logo"),
    ]

    for name, (w, h), theme_name, kind in jobs:
        theme = THEMES[theme_name]
        if kind == "icon":
            img = render_icon(w, h, theme)
        else:
            img = render_logo(w, h, theme, args.wordmark)
        out = os.path.join(args.out, name)
        save(img, out)
        print(f"{name:20s} {w}x{h} {img.mode}  {os.path.getsize(out)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
