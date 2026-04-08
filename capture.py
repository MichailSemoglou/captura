"""
capture.py — Screen Capture Logic
==================================
Responsibility (spec.md §4):
  Provide two pure functions that capture the primary display using `mss`
  and return a Pillow Image in RGB mode at logical (not physical) pixel
  resolution. All Retina / HiDPI downscaling is handled here.

Public API:
  capture_fullscreen() -> PIL.Image.Image
      Capture the entire primary display.

  capture_center_crop(ratio: tuple[int, int]) -> PIL.Image.Image
      Capture the largest centered rectangle of the given aspect ratio.

  capture_region(bbox: dict[str, int]) -> PIL.Image.Image
      Capture an arbitrary bounding box (logical pixels, from overlay).

Exceptions:
  ScreenCaptureError(Exception)
      Raised on any capture failure, including macOS permission denial,
      mss errors, or a zero-size image result.

macOS note (spec.md §9):
  Without Screen Recording permission, mss silently returns a black frame.
  platform_utils.has_screen_recording_permission() MUST be called before
  invoking these functions in the live application.

Does NOT:
  - Save files to disk.
  - Interact with the GUI or know about the application window.
  - Perform any network I/O.
"""

from __future__ import annotations

from functools import lru_cache

import mss
from PIL import Image


class ScreenCaptureError(Exception):
    """Raised when a screenshot capture attempt fails."""


def _check_black_frame(img: Image.Image) -> None:
    """Raise :class:`ScreenCaptureError` when *img* appears to be all black.

    macOS silently returns a completely black frame when Screen Recording
    permission is denied (instead of raising an error).  Sampling a small
    region at the image centre is sufficient to detect this case without
    scanning every pixel.

    Args:
        img: The captured image in RGB mode.

    Raises:
        ScreenCaptureError: When every sampled pixel is ``(0, 0, 0)``.
    """
    cx, cy = img.width // 2, img.height // 2
    # 5×5 sample centred on the image, clamped to valid coordinates.
    sample = img.crop((
        max(cx - 2, 0),
        max(cy - 2, 0),
        min(cx + 3, img.width),
        min(cy + 3, img.height),
    ))
    if not any(sample.tobytes()):
        raise ScreenCaptureError(
            "Capture returned a black frame — Screen Recording permission "
            "may be denied. Go to System Settings \u2192 Privacy & Security "
            "\u2192 Screen Recording and enable this application, then relaunch."
        )


@lru_cache(maxsize=1)
def _display_info() -> tuple[int, int, float]:  # pragma: no cover
    """Return ``(logical_width, logical_height, retina_scale)`` for the primary display.

    Opens a single hidden tkinter window to query logical screen dimensions,
    then compares against mss physical dimensions to derive the true HiDPI
    scale. The result is permanently cached so only one window is ever
    created per process lifetime.

    Returns:
        A 3-tuple ``(logical_width, logical_height, scale_factor)`` where
        *scale_factor* is ``1.0`` on non-Retina displays and ``2.0`` (or
        higher) on HiDPI Retina displays.

    Note:
        ``winfo_fpixels('1i') / 72`` is intentionally NOT used as the scale
        factor because it reflects the OS-configured DPI (e.g. 96 dpi →
        1.333) rather than the physical-to-logical pixel ratio.  On displays
        where OS DPI differs from the true pixel ratio this formula produces
        coordinates that overflow the physical screen, causing mss to return
        clipped or out-of-bounds frames.  The mss/tkinter ratio is the only
        reliable source of truth for the actual scale factor.
    """
    import tkinter as tk  # local import: tkinter used only for display introspection

    # Reuse an existing root window (e.g. the live CTk app window) to avoid
    # creating a second tk.Tk() instance, which is not allowed in tkinter.
    # When running standalone / in tests, the default root is None and we create
    # a temporary root that is immediately withdrawn and destroyed.
    # Prefer the semi-public helper _get_default_root() (added in Tk 8.6.x);
    # fall back to the private attribute so both old and new tkinter versions work.
    if callable(getattr(tk, "_get_default_root", None)):
        _existing: tk.Misc | None = tk._get_default_root()  # type: ignore[attr-defined]
    else:
        _existing = getattr(tk, "_default_root", None)
    if _existing is not None:
        logical_w: int = _existing.winfo_screenwidth()
        logical_h: int = _existing.winfo_screenheight()
    else:
        root = tk.Tk()
        root.withdraw()
        try:
            logical_w = root.winfo_screenwidth()
            logical_h = root.winfo_screenheight()
        finally:
            root.destroy()

    # Derive the true HiDPI scale from the ratio of mss physical pixels to
    # tkinter logical pixels. This is reliable on all display configurations:
    #   - Non-Retina (1:1):  scale = 1.0
    #   - Retina 2×:         scale = 2.0 (mss 3840 / tkinter 1920)
    #   - Non-standard DPI:  winfo_fpixels alone would be wrong; this is right
    with mss.mss() as sct:
        phys_w: int = sct.monitors[1]["width"]

    scale: float = phys_w / logical_w

    return logical_w, logical_h, scale


def warm_display_cache() -> None:
    """Pre-warm the :func:`_display_info` LRU cache on the calling thread.

    Must be called from the main (tkinter) thread before any background
    capture threads are started.  Once the cache is populated, subsequent
    calls to :func:`_display_info` from any thread are read-only and safe.
    """
    _display_info()


def capture_fullscreen() -> Image.Image:
    """Capture the entire primary display and return a PIL Image in RGB mode.

    On Retina (HiDPI) displays ``mss`` returns pixel data at the *physical*
    resolution (e.g. 2880×1800 for a 1440×900 logical display).  This
    function automatically downscales the result to logical resolution so
    every caller receives an image whose dimensions match the UI pixel grid.

    Returns:
        A :class:`PIL.Image.Image` in ``RGB`` mode at logical pixel
        resolution.

    Raises:
        ScreenCaptureError: On any capture failure, including a macOS Screen
            Recording permission denial or a zero-size grab result.
    """
    logical_w, logical_h, _scale = _display_info()

    try:
        with mss.mss() as sct:
            raw = sct.grab(sct.monitors[1])
    except Exception as exc:
        raise ScreenCaptureError(
            f"Full-screen capture failed: {exc}"
        ) from exc

    if raw.size[0] == 0 or raw.size[1] == 0:
        raise ScreenCaptureError(
            "Capture returned a zero-size image. "
            "Ensure Screen Recording permission is granted in "
            "System Settings → Privacy & Security → Screen Recording."
        )

    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    if img.size != (logical_w, logical_h):
        img = img.resize((logical_w, logical_h), Image.Resampling.LANCZOS)

    _check_black_frame(img)
    return img


def capture_center_crop(ratio: tuple[int, int]) -> Image.Image:
    """Capture the largest centered rectangle of the given aspect ratio.

    Computes the bounding box using the min-scale formula (spec.md §4a):
    the largest rectangle of ratio ``(rw, rh)`` that fits within the logical
    screen, centered on both axes. All coordinates use integer division to
    avoid fractional pixel values.

    On Retina displays the bounding box is scaled to physical pixels before
    being passed to ``mss``, then the image is downscaled back to logical
    dimensions before being returned.

    Args:
        ratio: A ``(width_units, height_units)`` tuple defining the target
               aspect ratio, e.g. ``(16, 9)`` for 16:9 widescreen.

    Returns:
        A :class:`PIL.Image.Image` in ``RGB`` mode at logical pixel
        resolution with dimensions matching the computed crop rectangle.

    Raises:
        ScreenCaptureError: On any capture failure.
    """
    logical_w, logical_h, scale = _display_info()

    rw, rh = ratio
    # Largest rectangle of ratio (rw:rh) that fits within the screen.
    fit_scale = min(logical_w / rw, logical_h / rh)
    crop_w: int = int(rw * fit_scale)
    crop_h: int = int(rh * fit_scale)

    # Center the crop rectangle on the screen (spec.md §4a).
    left_logical: int = (logical_w - crop_w) // 2
    top_logical: int = (logical_h - crop_h) // 2

    # Convert logical coordinates to physical pixels for mss.
    left: int = int(left_logical * scale)
    top: int = int(top_logical * scale)
    phys_w: int = int(crop_w * scale)
    phys_h: int = int(crop_h * scale)

    monitor = {
        "left": left,
        "top": top,
        "width": phys_w,
        "height": phys_h,
    }

    try:
        with mss.mss() as sct:
            raw = sct.grab(monitor)
    except Exception as exc:
        raise ScreenCaptureError(
            f"Center-crop {rw}:{rh} capture failed: {exc}"
        ) from exc

    if raw.size[0] == 0 or raw.size[1] == 0:
        raise ScreenCaptureError(
            f"Center-crop {rw}:{rh} capture returned a zero-size image. "
            "Check Screen Recording permission and screen resolution."
        )

    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    # Downscale to logical crop dimensions if mss returned physical pixels.
    if img.size != (crop_w, crop_h):
        img = img.resize((crop_w, crop_h), Image.Resampling.LANCZOS)

    _check_black_frame(img)
    return img


def capture_region(bbox: dict[str, int]) -> Image.Image:
    """Capture an arbitrary screen region and return a PIL Image in RGB mode.

    The bounding box must be specified in **logical pixels**.  On Retina
    displays the coordinates are multiplied by the HiDPI scale factor before
    passing to ``mss``, and the result is downscaled back to logical
    dimensions before being returned.

    Args:
        bbox: A dict with keys ``"left"``, ``"top"``, ``"width"``,
              ``"height"`` all given in logical pixel coordinates.  The
              custom-region overlay guarantees a minimum size of 10×10 px
              before calling this function.

    Returns:
        A :class:`PIL.Image.Image` in ``RGB`` mode at logical pixel
        resolution.

    Raises:
        ScreenCaptureError: On any capture failure.
    """
    _logical_w, _logical_h, scale = _display_info()

    left_logical: int = bbox["left"]
    top_logical: int = bbox["top"]
    width_logical: int = bbox["width"]
    height_logical: int = bbox["height"]

    # Convert logical coordinates to physical pixels for mss.
    left: int = int(left_logical * scale)
    top: int = int(top_logical * scale)
    phys_w: int = int(width_logical * scale)
    phys_h: int = int(height_logical * scale)

    monitor = {
        "left": left,
        "top": top,
        "width": phys_w,
        "height": phys_h,
    }

    try:
        with mss.mss() as sct:
            raw = sct.grab(monitor)
    except Exception as exc:
        raise ScreenCaptureError(
            f"Region capture failed: {exc}"
        ) from exc

    if raw.size[0] == 0 or raw.size[1] == 0:
        raise ScreenCaptureError(
            "Region capture returned a zero-size image. "
            "Check Screen Recording permission."
        )

    img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    # Downscale to logical region dimensions if mss returned physical pixels.
    if img.size != (width_logical, height_logical):
        img = img.resize((width_logical, height_logical), Image.Resampling.LANCZOS)

    _check_black_frame(img)
    return img
