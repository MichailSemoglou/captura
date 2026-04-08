"""
tests/test_preview.py — Unit tests for preview.py
==================================================
Tests to implement (plan.md T-04):

  P-01  fit_image_to_canvas()  Landscape image fits within a landscape canvas
  P-02  fit_image_to_canvas()  Portrait image fits within a portrait canvas
  P-03  fit_image_to_canvas()  Image exactly matching canvas size is returned as-is
  P-04  fit_image_to_canvas()  Output dimensions never exceed canvas dimensions
  P-05  fit_image_to_canvas()  Aspect ratio is preserved (within 1 px rounding error)
  P-06  fit_image_to_canvas()  Works with a square canvas and a non-square image

Mocking strategy:
  No mocking required. Use small in-memory images created with:
    PIL.Image.new("RGB", (width, height), color=(r, g, b))
  These are pure Pillow operations with no I/O or display dependency.

Run:
  pytest tests/test_preview.py -v
  pytest tests/test_preview.py -v --cov=preview --cov-report=term-missing
"""

from __future__ import annotations

from PIL import Image

import preview

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _img(w: int, h: int) -> Image.Image:
    return Image.new("RGB", (w, h), color=(128, 128, 128))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_p01_landscape_image_fits_landscape_canvas():
    """P-01: A landscape image is scaled to fit within a landscape canvas."""
    img = _img(1440, 900)
    result = preview.fit_image_to_canvas(img, 720, 450)
    assert result.size[0] <= 720
    assert result.size[1] <= 450


def test_p02_portrait_image_fits_portrait_canvas():
    """P-02: A portrait image is scaled to fit within a portrait canvas."""
    img = _img(900, 1440)
    result = preview.fit_image_to_canvas(img, 450, 720)
    assert result.size[0] <= 450
    assert result.size[1] <= 720


def test_p03_image_exactly_matching_canvas_returned_as_is():
    """P-03: An image the same size as the canvas is returned unchanged (same object)."""
    img = _img(640, 400)
    result = preview.fit_image_to_canvas(img, 640, 400)
    assert result is img


def test_p04_output_dimensions_never_exceed_canvas():
    """P-04: Resized image width and height are always ≤ canvas dimensions."""
    img = _img(2880, 1800)
    result = preview.fit_image_to_canvas(img, 690, 430)
    assert result.size[0] <= 690
    assert result.size[1] <= 430


def test_p05_aspect_ratio_is_preserved():
    """P-05: The aspect ratio of the output is within 2% of the source ratio."""
    img = _img(1440, 900)  # ratio = 1.6
    result = preview.fit_image_to_canvas(img, 600, 600)
    rw, rh = result.size
    assert abs((rw / rh) - (1440 / 900)) < 0.02


def test_p06_square_canvas_non_square_image():
    """P-06: A wide image placed in a square canvas is constrained by its width."""
    img = _img(800, 400)  # 2:1 ratio
    result = preview.fit_image_to_canvas(img, 400, 400)
    # scale = min(400/800, 400/400, 1.0) = 0.5 → (400, 200)
    assert result.size == (400, 200)


def test_p07_image_smaller_than_canvas_is_not_upscaled():
    """P-07: An image smaller than the canvas is returned unchanged (no upscaling)."""
    img = _img(200, 150)
    result = preview.fit_image_to_canvas(img, 800, 600)
    assert result is img

