"""
storage.py — File Persistence
==============================
Responsibility (spec.md §4):
  Handle all filesystem concerns: generate timestamped filenames, resolve
  and create the ~/Screenshots/ save directory, and save PIL images as PNG.

Public API:
  StorageError(Exception)
      Raised on any file-system failure (save error, path-is-a-file, etc.).

  generate_filename(dt: datetime, mode: str) -> str
      Return a filename of the form:
          screenshot_YYYY-MM-DD_HH-MM-SS_[mode].png
      where *mode* is the capture-mode suffix (e.g. ``"fullscreen"``,
      ``"16x9"``, ``"custom"``).
      Rapid-fire duplicate timestamps are disambiguated by appending a
      counter suffix: screenshot_YYYY-MM-DD_HH-MM-SS_[mode]_1.png, …

  get_screenshots_dir() -> pathlib.Path
      Return ~/Screenshots/, creating it (with parents) if absent.
      Raises StorageError if the path already exists as a file.

  save_image(
      image:     PIL.Image.Image,
      directory: pathlib.Path,
      filename:  str,
  ) -> pathlib.Path
      Save the image as a PNG file in the given directory.
      Returns the full path of the saved file.
      Raises StorageError on any OSError.

Does NOT:
  - Perform screen captures.
  - Interact with the GUI.
  - Open files or folders in Finder.
"""

from __future__ import annotations

import os
import pathlib
import re
from datetime import datetime

from PIL import Image


class StorageError(Exception):
    """Raised when a file save operation fails."""


def generate_filename(dt: datetime, mode: str) -> str:
    """Return a timestamped PNG filename for the given datetime and capture mode.

    Format: ``screenshot_YYYY-MM-DD_HH-MM-SS_[mode].png``

    All date/time components are zero-padded to a fixed width
    (e.g. month 1 becomes ``01``).

    Args:
        dt:   The datetime to embed in the filename.
        mode: The capture-mode suffix string, e.g. ``"fullscreen"``,
              ``"16x9"``, or ``"custom"``. Any characters outside
              ``[A-Za-z0-9._-]`` are replaced with underscores and the
              result is truncated to 32 characters.

    Returns:
        A filename string such as
        ``"screenshot_2026-04-05_14-30-45_fullscreen.png"``.
    """
    ts = dt.strftime("screenshot_%Y-%m-%d_%H-%M-%S")
    safe_mode = re.sub(r"[^A-Za-z0-9._-]+", "_", mode).strip("_")[:32] or "unknown"
    return f"{ts}_{safe_mode}.png"


def get_screenshots_dir() -> pathlib.Path:
    """Return the ``~/Screenshots/`` directory, creating it when absent.

    Returns:
        A :class:`pathlib.Path` pointing to ``~/Screenshots/``.

    Raises:
        StorageError: If ``~/Screenshots`` already exists as a *file*
            rather than a directory.
    """
    directory = pathlib.Path.home() / "Screenshots"
    if directory.is_file():
        raise StorageError(
            f"Cannot use '{directory}' as the screenshots directory: "
            "the path already exists as a file."
        )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_image(
    image: Image.Image,
    directory: pathlib.Path,
    filename: str,
) -> pathlib.Path:
    """Save a PIL image as a PNG file inside *directory*.

    If a file with *filename* already exists in *directory*, a numeric
    counter suffix is appended to avoid overwriting existing screenshots:
    ``_1``, ``_2``, … up to ``_99``.

    Args:
        image:     The PIL image to save.
        directory: Target directory.  Should already exist (created by
                   :func:`get_screenshots_dir`).
        filename:  Base filename, e.g.
                   ``"screenshot_2026-04-05_14-30-45.png"``.

    Returns:
        The :class:`pathlib.Path` of the successfully saved file.

    Raises:
        StorageError: If *directory* is a file rather than a directory, if
            no unique filename can be found within 99 counter attempts, or
            if any :class:`OSError` occurs during the PNG write.
    """
    if directory.is_file():
        raise StorageError(
            f"Cannot save to '{directory}': the path is a file, not a directory."
        )

    stem = pathlib.Path(filename).stem
    suffix = pathlib.Path(filename).suffix
    candidates = [directory / filename] + [
        directory / f"{stem}_{counter}{suffix}" for counter in range(1, 100)
    ]

    for candidate in candidates:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        except OSError as exc:
            raise StorageError(
                f"Failed to save screenshot to '{candidate}': {exc}"
            ) from exc
        try:
            with os.fdopen(fd, "wb") as fp:
                image.save(fp, format="PNG")
        except OSError as exc:
            raise StorageError(
                f"Failed to save screenshot to '{candidate}': {exc}"
            ) from exc
        return candidate

    raise StorageError(
        f"Could not find a free filename for '{filename}' after "
        "99 attempts. Clear old screenshots from the output folder."
    )
