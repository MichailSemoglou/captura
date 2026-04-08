"""
tests/test_beautify.py — Unit tests for beautify.py
=====================================================

Tests cover:
  B-01  Output image size equals (img_w + 2*padding, img_h + 2*padding)
        when shadow_size="none".
  B-02  Output mode is always "RGB".
  B-03  Zero padding: canvas equals original image size.
  B-04  Gradient background: different gradient indices produce different pixels.
  B-05  Solid background: output background colour matches the requested colour.
  B-06  Shadow extends canvas beyond the symmetric padding area.
  B-07  Rounded corners: corner pixel is fully transparent before RGB conversion
        (verified via RGBA intermediate).
  B-08  All 8 gradient presets and 4 solid presets produce valid RGB images.
  B-09  BeautifySettings defaults are sane values.
"""

from __future__ import annotations

import pytest
from PIL import Image

import beautify
from beautify import BeautifySettings, apply_beautification

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solid(w: int = 120, h: int = 80, color: tuple = (128, 128, 128)) -> Image.Image:
    """Return a plain RGB image filled with *color*."""
    return Image.new("RGB", (w, h), color)


# ---------------------------------------------------------------------------
# B-01  Output size with shadow="none"
# ---------------------------------------------------------------------------

def test_output_size_no_shadow() -> None:
    img = _solid(100, 80)
    result = apply_beautification(
        img, BeautifySettings(padding=20, corner_radius=0, shadow_size="none")
    )
    assert result.width == 100 + 2 * 20
    assert result.height == 80 + 2 * 20


def test_output_size_gradient_no_shadow() -> None:
    img = _solid(200, 150)
    result = apply_beautification(
        img,
        BeautifySettings(
            bg_type="gradient", gradient_index=2, padding=40,
            corner_radius=0, shadow_size="none",
        ),
    )
    assert result.width == 200 + 2 * 40
    assert result.height == 150 + 2 * 40


# ---------------------------------------------------------------------------
# B-02  Output mode is RGB
# ---------------------------------------------------------------------------

def test_output_mode_rgb() -> None:
    result = apply_beautification(_solid(), BeautifySettings())
    assert result.mode == "RGB"


def test_output_mode_rgba_input_becomes_rgb() -> None:
    img = Image.new("RGBA", (100, 80), (200, 200, 200, 255))
    result = apply_beautification(img, BeautifySettings(corner_radius=0, shadow_size="none"))
    assert result.mode == "RGB"


# ---------------------------------------------------------------------------
# B-03  Zero padding
# ---------------------------------------------------------------------------

def test_zero_padding_no_shadow() -> None:
    img = _solid(100, 80)
    result = apply_beautification(
        img, BeautifySettings(padding=0, corner_radius=0, shadow_size="none")
    )
    assert result.width == 100
    assert result.height == 80


# ---------------------------------------------------------------------------
# B-04  Different gradients produce different images
# ---------------------------------------------------------------------------

def test_different_gradients_differ() -> None:
    img = _solid(80, 60)
    result0 = apply_beautification(
        img, BeautifySettings(bg_type="gradient", gradient_index=0,
                              padding=30, corner_radius=0, shadow_size="none")
    )
    result1 = apply_beautification(
        img, BeautifySettings(bg_type="gradient", gradient_index=2,
                              padding=30, corner_radius=0, shadow_size="none")
    )
    # The top-left corner pixel should differ across gradient presets.
    assert result0.getpixel((0, 0)) != result1.getpixel((0, 0))


# ---------------------------------------------------------------------------
# B-05  Solid background colour
# ---------------------------------------------------------------------------

def test_solid_background_colour() -> None:
    img = _solid(50, 50)
    bg_color = (40, 40, 50)
    result = apply_beautification(
        img,
        BeautifySettings(
            bg_type="solid", bg_color=bg_color,
            padding=20, corner_radius=0, shadow_size="none",
        ),
    )
    # Top-left corner pixel (in the padding zone) should match bg_color.
    assert result.getpixel((0, 0)) == bg_color


# ---------------------------------------------------------------------------
# B-06  Shadow does NOT change canvas size (screenshot stays centred)
# ---------------------------------------------------------------------------

def test_shadow_does_not_extend_canvas() -> None:
    """Canvas dimensions are always img + 2*padding regardless of shadow size.

    The shadow is composited within the existing padding so that the
    screenshot remains perfectly centred in the output image.
    """
    img = _solid(100, 80)
    base = apply_beautification(
        img, BeautifySettings(padding=30, corner_radius=0, shadow_size="none")
    )
    with_shadow = apply_beautification(
        img, BeautifySettings(padding=30, corner_radius=0, shadow_size="large")
    )
    assert with_shadow.width == base.width
    assert with_shadow.height == base.height


# ---------------------------------------------------------------------------
# B-07  Rounded corners make the corner pixel transparent (pre-conversion)
# ---------------------------------------------------------------------------

def test_rounded_corners_transparency() -> None:
    """The RGBA mask applied for rounded corners sets corner pixels to alpha=0."""
    from beautify import _apply_rounded_corners

    img = _solid(100, 100, (255, 0, 0))
    result = _apply_rounded_corners(img, radius=20)
    assert result.mode == "RGBA"
    # Corner pixel should be fully transparent.
    assert result.getpixel((0, 0))[3] == 0
    # Centre pixel should be fully opaque.
    assert result.getpixel((50, 50))[3] == 255


# ---------------------------------------------------------------------------
# B-08  All gradient and solid presets produce valid RGB images
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("idx", range(len(beautify.GRADIENTS)))
def test_all_gradient_presets(idx: int) -> None:
    img = _solid(60, 40)
    result = apply_beautification(
        img,
        BeautifySettings(bg_type="gradient", gradient_index=idx,
                         padding=10, corner_radius=0, shadow_size="none"),
    )
    assert result.mode == "RGB"
    assert result.width > 0


@pytest.mark.parametrize("color", beautify.SOLID_COLORS)
def test_all_solid_presets(color: tuple) -> None:
    img = _solid(60, 40)
    result = apply_beautification(
        img,
        BeautifySettings(bg_type="solid", bg_color=color,
                         padding=10, corner_radius=0, shadow_size="none"),
    )
    assert result.mode == "RGB"
    assert result.getpixel((0, 0)) == color


# ---------------------------------------------------------------------------
# B-09  BeautifySettings defaults
# ---------------------------------------------------------------------------

def test_default_settings_are_sane() -> None:
    s = BeautifySettings()
    assert s.bg_type == "gradient"
    assert 0 <= s.gradient_index < len(beautify.GRADIENTS)
    assert s.padding >= 0
    assert s.corner_radius >= 0
    assert s.shadow_size in ("none", "small", "medium", "large")
