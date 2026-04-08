"""
tests/test_capture.py — Unit tests for capture.py
==================================================
Tests to implement (plan.md T-06):

  C-01  capture_fullscreen()    Returns a PIL.Image in RGB mode
  C-02  capture_fullscreen()    Raises ScreenCaptureError when mss.grab raises
  C-03  capture_fullscreen()    Downscales image to logical resolution at 2× scale
  C-04  capture_fullscreen()    Raises ScreenCaptureError for a zero-size image
  C-05  capture_center_crop()   16:9 on 1440×900 → image dims 1440×810
  C-06  capture_center_crop()   1:1 on 1440×900 → image dims 900×900, bbox centered
  C-07  capture_center_crop()   Raises ScreenCaptureError on mss failure
  C-08  capture_center_crop()   Passes only integer coordinates to mss
  C-09  capture_center_crop()   Downscales physical→logical at 2× scale
  C-10  capture_center_crop()   Raises ScreenCaptureError for a zero-size image
  C-11  capture_fullscreen()    Raises ScreenCaptureError when frame is all-black
  C-12  capture_center_crop()   Raises ScreenCaptureError when frame is all-black
  C-13  capture_region()        Returns image with correct dimensions for given bbox
  C-14  capture_region()        Raises ScreenCaptureError on mss failure

Mocking strategy:
  Use mocker.patch("mss.mss") to inject a fake sct context manager.
  Fake monitor dict: {"width": 1440, "height": 900, "left": 0, "top": 0}
  The mss context manager mock requires explicit __enter__ / __exit__ /
  sct.monitors attribute assignment on a MagicMock instance.
  mss is never called against a real display during tests.

Run:
  pytest tests/test_capture.py -v
  pytest tests/test_capture.py -v --cov=capture --cov-report=term-missing
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PIL import Image

import capture
from capture import ScreenCaptureError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw(width: int, height: int) -> MagicMock:
    """Return a fake mss ScreenShot with non-black BGRA pixel data."""
    raw = MagicMock()
    raw.size = (width, height)
    # Use a mid-grey pixel (B=128, G=128, R=128, A=255) so the black-frame
    # guard in capture.py does NOT trigger on normal test images.
    pixel = bytes([128, 128, 128, 255])
    raw.bgra = pixel * (width * height)
    return raw


def _make_raw_black(width: int, height: int) -> MagicMock:
    """Return a fake mss ScreenShot whose every pixel is (0, 0, 0, 0) — all black."""
    raw = MagicMock()
    raw.size = (width, height)
    raw.bgra = bytes(width * height * 4)  # all zeros
    return raw


def _patch_mss_fullscreen(
    mocker,
    raw: MagicMock,
    phys_w: int = 1440,
    phys_h: int = 900,
) -> MagicMock:
    """Patch ``mss.mss`` for fullscreen captures (requires ``sct.monitors[1]``)."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.monitors = [
        {"left": 0, "top": 0, "width": phys_w, "height": phys_h},  # [0] virtual
        {"left": 0, "top": 0, "width": phys_w, "height": phys_h},  # [1] primary
    ]
    mock_sct.grab.return_value = raw
    mocker.patch("mss.mss", return_value=mock_sct)
    return mock_sct


def _patch_mss_region(mocker, raw: MagicMock) -> MagicMock:
    """Patch ``mss.mss`` for region captures (no ``monitors`` access needed)."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.grab.return_value = raw
    mocker.patch("mss.mss", return_value=mock_sct)
    return mock_sct


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_display_info(mocker):
    """Replace ``_display_info`` so no tkinter window is opened during tests.

    Default logical screen: 1440×900 at 1× scale.
    Individual tests may override this by patching again.
    """
    mocker.patch("capture._display_info", return_value=(1440, 900, 1.0))


# ---------------------------------------------------------------------------
# capture_fullscreen() — C-01 through C-04
# ---------------------------------------------------------------------------

def test_c01_capture_fullscreen_returns_rgb_image(mocker):
    """C-01: capture_fullscreen() returns a PIL.Image in RGB mode."""
    raw = _make_raw(1440, 900)
    _patch_mss_fullscreen(mocker, raw)

    img = capture.capture_fullscreen()

    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"


def test_c02_capture_fullscreen_raises_on_mss_error(mocker):
    """C-02: capture_fullscreen() raises ScreenCaptureError when mss.grab raises."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.monitors = [
        {"left": 0, "top": 0, "width": 1440, "height": 900},
        {"left": 0, "top": 0, "width": 1440, "height": 900},
    ]
    mock_sct.grab.side_effect = Exception("permission denied by macOS")
    mocker.patch("mss.mss", return_value=mock_sct)

    with pytest.raises(ScreenCaptureError, match="permission denied by macOS"):
        capture.capture_fullscreen()


def test_c03_capture_fullscreen_downscales_at_retina_scale(mocker):
    """C-03: capture_fullscreen() downscales physical→logical resolution at 2× scale."""
    # Retina: logical 1440×900, physical 2880×1800
    mocker.patch("capture._display_info", return_value=(1440, 900, 2.0))
    raw = _make_raw(2880, 1800)
    _patch_mss_fullscreen(mocker, raw, phys_w=2880, phys_h=1800)

    img = capture.capture_fullscreen()

    assert img.size == (1440, 900)


def test_c04_capture_fullscreen_raises_on_zero_size_image(mocker):
    """C-04: capture_fullscreen() raises ScreenCaptureError for a zero-size grab."""
    raw = _make_raw(0, 0)
    _patch_mss_fullscreen(mocker, raw)

    with pytest.raises(ScreenCaptureError):
        capture.capture_fullscreen()


# ---------------------------------------------------------------------------
# capture_center_crop() — C-05 through C-10, C-12
# ---------------------------------------------------------------------------

def test_c05_capture_center_crop_16x9_correct_dimensions(mocker):
    """C-05: capture_center_crop((16, 9)) on 1440×900 returns a 1440×810 image.

    fit_scale = min(1440/16, 900/9) = min(90, 100) = 90
    crop_w = 16*90 = 1440, crop_h = 9*90 = 810
    """
    raw = _make_raw(1440, 810)
    mock_sct = _patch_mss_region(mocker, raw)

    img = capture.capture_center_crop((16, 9))

    assert img.size == (1440, 810)
    bbox = mock_sct.grab.call_args[0][0]
    # left = (1440-1440)//2 = 0, top = (900-810)//2 = 45
    assert bbox["left"] == 0
    assert bbox["top"] == 45
    assert bbox["width"] == 1440
    assert bbox["height"] == 810


def test_c06_capture_center_crop_1x1_correct_dimensions_and_centered(mocker):
    """C-06: capture_center_crop((1, 1)) on 1440×900 returns a 900×900 image.

    fit_scale = min(1440/1, 900/1) = 900
    crop_w = crop_h = 900
    left = (1440-900)//2 = 270, top = 0
    """
    raw = _make_raw(900, 900)
    mock_sct = _patch_mss_region(mocker, raw)

    img = capture.capture_center_crop((1, 1))

    assert img.size == (900, 900)
    bbox = mock_sct.grab.call_args[0][0]
    assert bbox["left"] == 270
    assert bbox["top"] == 0
    assert bbox["width"] == 900
    assert bbox["height"] == 900


def test_c07_capture_center_crop_raises_on_mss_error(mocker):
    """C-07: capture_center_crop() raises ScreenCaptureError on mss failure."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.grab.side_effect = Exception("capture unavailable")
    mocker.patch("mss.mss", return_value=mock_sct)

    with pytest.raises(ScreenCaptureError, match="capture unavailable"):
        capture.capture_center_crop((16, 9))


def test_c08_capture_center_crop_uses_integer_coords(mocker):
    """C-08: capture_center_crop() passes only integer coordinates to mss.

    Uses ratio (4, 3) on 1440×900:
      fit_scale = min(1440/4, 900/3) = min(360, 300) = 300
      crop_w = 1200, crop_h = 900
      left = 120, top = 0
    All bbox values must be plain Python ints.
    """
    raw = _make_raw(1200, 900)
    mock_sct = _patch_mss_region(mocker, raw)

    capture.capture_center_crop((4, 3))

    bbox = mock_sct.grab.call_args[0][0]
    assert all(
        isinstance(v, int) for v in bbox.values()
    ), f"Non-integer bbox coord(s): {bbox}"
    assert bbox["left"] == 120
    assert bbox["top"] == 0
    assert bbox["width"] == 1200
    assert bbox["height"] == 900


def test_c09_capture_center_crop_downscales_at_retina_scale(mocker):
    """C-09: capture_center_crop() downscales physical→logical at 2× scale.

    Retina 1440×900 at 2×.  For 16:9: physical grab is 2880×1620;
    result must be logical 1440×810.
    """
    mocker.patch("capture._display_info", return_value=(1440, 900, 2.0))
    raw = _make_raw(2880, 1620)  # mss returns physical pixels
    _patch_mss_region(mocker, raw)

    img = capture.capture_center_crop((16, 9))

    assert img.size == (1440, 810)


def test_c10_capture_center_crop_raises_on_zero_size_image(mocker):
    """C-10: capture_center_crop() raises ScreenCaptureError for a zero-size grab."""
    raw = _make_raw(0, 0)
    _patch_mss_region(mocker, raw)

    with pytest.raises(ScreenCaptureError):
        capture.capture_center_crop((16, 9))


def test_c11_capture_fullscreen_raises_on_black_frame(mocker):
    """C-11: capture_fullscreen() raises ScreenCaptureError if the frame is all-black.

    macOS silently returns an all-black frame when Screen Recording permission
    is denied.  The black-frame guard in capture.py must detect and raise.
    """
    raw = _make_raw_black(1440, 900)
    _patch_mss_fullscreen(mocker, raw)

    with pytest.raises(ScreenCaptureError, match="black frame"):
        capture.capture_fullscreen()


def test_c12_capture_center_crop_raises_on_black_frame(mocker):
    """C-12: capture_center_crop() raises ScreenCaptureError if the frame is all-black."""
    raw = _make_raw_black(1440, 810)
    _patch_mss_region(mocker, raw)

    with pytest.raises(ScreenCaptureError, match="black frame"):
        capture.capture_center_crop((16, 9))


# ---------------------------------------------------------------------------
# capture_region() — C-13 and C-14
# ---------------------------------------------------------------------------

def test_c13_capture_region_returns_image_with_correct_dimensions(mocker):
    """C-13: capture_region() returns an RGB image matching the given bbox size."""
    bbox = {"left": 100, "top": 50, "width": 400, "height": 300}
    raw = _make_raw(400, 300)
    _patch_mss_region(mocker, raw)

    img = capture.capture_region(bbox)

    assert isinstance(img, Image.Image)
    assert img.mode == "RGB"
    assert img.size == (400, 300)


def test_c14_capture_region_raises_on_mss_error(mocker):
    """C-14: capture_region() raises ScreenCaptureError on mss failure."""
    mock_sct = MagicMock()
    mock_sct.__enter__ = MagicMock(return_value=mock_sct)
    mock_sct.__exit__ = MagicMock(return_value=False)
    mock_sct.grab.side_effect = Exception("region grab failed")
    mocker.patch("mss.mss", return_value=mock_sct)

    with pytest.raises(ScreenCaptureError, match="region grab failed"):
        capture.capture_region({"left": 0, "top": 0, "width": 200, "height": 150})


