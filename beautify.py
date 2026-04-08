"""
beautify.py — Screenshot Beautification
=========================================
Applies a styled background, padding, rounded corners, and a drop shadow
to a raw PIL screenshot.

Public API
----------
BeautifySettings   — dataclass holding all beautification parameters.
GRADIENTS          — list of 8 (left_rgb, right_rgb) gradient presets.
SOLID_COLORS       — list of 4 solid-color presets as (R, G, B) tuples.
apply_beautification(img, settings) -> PIL.Image (RGB)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------------------
# Palette presets
# ---------------------------------------------------------------------------

# 8 left-to-right gradient presets: (left_rgb, right_rgb).
GRADIENTS: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = [
    ((99, 102, 241), (168, 85, 247)),   # Indigo → Purple
    ((59, 130, 246), (16, 185, 129)),   # Blue → Teal
    ((249, 115, 22), (239, 68, 68)),    # Orange → Red
    ((236, 72, 153), (168, 85, 247)),   # Pink → Purple
    ((20, 184, 166), (59, 130, 246)),   # Teal → Blue
    ((245, 158, 11), (234, 88, 12)),    # Amber → Orange
    ((6, 182, 212), (16, 185, 129)),    # Cyan → Emerald
    ((251, 191, 36), (244, 63, 94)),    # Gold → Rose
]

# 4 solid-colour presets as RGB tuples.
SOLID_COLORS: list[tuple[int, int, int]] = [
    (15, 15, 20),    # Near-black
    (40, 40, 50),    # Dark graphite
    (240, 240, 245), # Near-white
    (100, 149, 237), # Cornflower blue
]

# ---------------------------------------------------------------------------
# Shadow parameters — (x/y pixel offset, gaussian blur radius)
# ---------------------------------------------------------------------------

_SHADOW_PARAMS: dict[str, tuple[int, int]] = {
    "none":   (0, 0),
    "small":  (4, 6),
    "medium": (8, 14),
    "large":  (16, 26),
}

# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------


@dataclass
class BeautifySettings:
    """All parameters that control output beautification."""

    bg_type: Literal["gradient", "solid"] = "gradient"
    gradient_index: int = 0
    bg_color: tuple[int, int, int] = (30, 30, 40)
    padding: int = 60
    corner_radius: int = 12
    shadow_size: Literal["none", "small", "medium", "large"] = "medium"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_gradient_bg(
    width: int,
    height: int,
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
) -> Image.Image:
    """Return a left-to-right linear gradient image in RGB mode.

    Builds a single-pixel-high gradient row via ``Image.putdata`` (one Python
    list comprehension, no per-column draw calls) then scales it to full height
    using ``Image.resize`` with nearest-neighbour interpolation.  This is
    significantly faster than the O(width × height) ``ImageDraw.line`` loop for
    large canvases.
    """
    w = max(width, 1)
    step = 1.0 / max(w - 1, 1)
    row_pixels = [
        (
            round(c1[0] + (c2[0] - c1[0]) * x * step),
            round(c1[1] + (c2[1] - c1[1]) * x * step),
            round(c1[2] + (c2[2] - c1[2]) * x * step),
        )
        for x in range(w)
    ]
    row = Image.new("RGB", (w, 1))
    row.putdata(row_pixels)
    return row.resize((width, height), resample=Image.Resampling.NEAREST)


def _apply_rounded_corners(img: Image.Image, radius: int) -> Image.Image:
    """Return *img* converted to RGBA with rounded corners applied via a mask."""
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        [0, 0, img.width - 1, img.height - 1],
        radius=radius,
        fill=255,
    )
    result = Image.new("RGBA", img.size, (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_beautification(
    img: Image.Image,
    settings: BeautifySettings,
) -> Image.Image:
    """Composite *img* onto a styled background and return the result as RGB.

    The canvas is always sized to ``img`` + ``settings.padding`` on **every**
    side, keeping the screenshot perfectly centred.  The drop shadow is drawn
    within that padding; it may be softly clipped only when padding is very
    small relative to the shadow size.

    Args:
        img:      Raw screenshot in any Pillow mode.
        settings: Beautification parameters (see :class:`BeautifySettings`).

    Returns:
        New Pillow ``Image`` in RGB mode.
    """
    p = settings.padding
    s_offset, s_blur = _SHADOW_PARAMS.get(settings.shadow_size, (0, 0))

    # Canvas is always symmetric: equal padding on every side so that the
    # screenshot is centred.  The shadow is drawn within the padding area and
    # may be softly clipped at the canvas edge only when the padding is
    # unusually small relative to the shadow size — acceptable behaviour.
    canvas_w = img.width + 2 * p
    canvas_h = img.height + 2 * p

    # Build background layer.
    if settings.bg_type == "gradient":
        idx = max(0, min(settings.gradient_index, len(GRADIENTS) - 1))
        c1, c2 = GRADIENTS[idx]
        bg = _make_gradient_bg(canvas_w, canvas_h, c1, c2).convert("RGBA")
    else:
        bg = Image.new("RGBA", (canvas_w, canvas_h), (*settings.bg_color, 255))

    # Drop shadow (blurred dark rectangle offset below the screenshot).
    if s_offset > 0 or s_blur > 0:
        shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(shadow_layer)
        sx, sy = p + s_offset, p + s_offset
        draw.rectangle(
            [sx, sy, sx + img.width - 1, sy + img.height - 1],
            fill=(0, 0, 0, 140),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(s_blur))
        bg = Image.alpha_composite(bg, shadow_layer)

    # Apply rounded corners to the screenshot.
    screenshot: Image.Image
    if settings.corner_radius > 0:
        screenshot = _apply_rounded_corners(img, settings.corner_radius)
    else:
        screenshot = img.convert("RGBA")

    # Paste screenshot centred in the padded area.
    bg.paste(screenshot, (p, p), screenshot)

    return bg.convert("RGB")
