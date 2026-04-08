"""
preview.py — Preview Image Preparation
=======================================
Responsibility (spec.md §4):
  Provide a single pure utility function that resizes a PIL Image to fit
  within a given canvas area while preserving aspect ratio. The returned
  image is ready to be wrapped in an ImageTk.PhotoImage for display on a
  tkinter Canvas widget.

Public API:
  fit_image_to_canvas(
      image: PIL.Image.Image,
      canvas_width: int,
      canvas_height: int,
  ) -> PIL.Image.Image
      Resize the image to fit within (canvas_width × canvas_height) using
      Lanczos resampling. Aspect ratio is always preserved. The function
      never upscales an image smaller than the canvas. The caller's image
      object is not mutated.

Does NOT:
  - Import or interact with tkinter or customtkinter.
  - Create or manage PhotoImage objects (that is app.py's responsibility
    to prevent garbage collection).
  - Write anything to disk.
"""

from __future__ import annotations

from PIL import Image


def fit_image_to_canvas(
    image: Image.Image,
    canvas_width: int,
    canvas_height: int,
) -> Image.Image:
    """Resize *image* to fit within a canvas area while preserving aspect ratio.

    Lanczos resampling is used for all downscaling operations. The
    function **never upscales** an image that is already smaller than the
    canvas — in that case the original image object is returned unchanged.

    Args:
        image: Source PIL image to resize.
        canvas_width: Available canvas width in pixels.
        canvas_height: Available canvas height in pixels.

    Returns:
        A :class:`PIL.Image.Image` whose dimensions fit within
        ``canvas_width × canvas_height`` with the original aspect ratio
        intact, or the original *image* unchanged when it is already at or
        below the canvas size.
    """
    img_w, img_h = image.size
    if img_w == 0 or img_h == 0 or canvas_width <= 0 or canvas_height <= 0:
        return image

    # Scale factor to fit; cap at 1.0 to prevent upscaling.
    scale = min(canvas_width / img_w, canvas_height / img_h, 1.0)

    new_w = int(img_w * scale)
    new_h = int(img_h * scale)

    if (new_w, new_h) == (img_w, img_h):
        return image

    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

