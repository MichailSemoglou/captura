"""
platform_utils.py — macOS Platform Utilities
=============================================
Responsibility (spec.md §4, §9):
  Isolate all macOS-specific system interactions so they never bleed into
  core capture or storage logic (Constitution §II).

Public API:
  has_screen_recording_permission() -> bool
      Attempt a 1×1 pixel capture with mss. Returns True on success,
      False if macOS raises any exception (permission denied).

  prompt_screen_recording_permission() -> None
      Open System Settings → Privacy & Security → Screen Recording via
      the macOS `open` command with the x-apple.systempreferences URL.
      Does not raise; if the open call fails, the user can navigate manually.

  open_folder(path: pathlib.Path) -> None
      Open the given folder in macOS Finder using `subprocess.run(["open", …])`.
      Logs to stderr on CalledProcessError; does NOT re-raise (non-critical).

Constants:
  SCREEN_RECORDING_PREFS_URL : str
      The URL that opens the Screen Recording privacy pane directly.

Does NOT:
  - Perform full-resolution screenshot captures.
  - Interact with GUI widgets beyond being called from app.py.
"""

from __future__ import annotations

import logging
import pathlib
import subprocess

import mss

SCREEN_RECORDING_PREFS_URL: str = (
    "x-apple.systempreferences:"
    "com.apple.preference.security?Privacy_ScreenCapture"
)


def has_screen_recording_permission() -> bool:
    """Return ``True`` if Screen Recording permission is granted.

    Performs a minimal 1×1 pixel capture attempt with mss. If macOS
    blocks the capture (returning a permission error or raising an
    exception), returns ``False``.

    Returns:
        ``True`` when the 1×1 capture succeeds; ``False`` otherwise.
    """
    try:
        with mss.mss() as sct:
            sct.grab({"top": 0, "left": 0, "width": 1, "height": 1})
        return True
    except Exception:
        return False


def prompt_screen_recording_permission() -> None:
    """Open the Screen Recording privacy pane in macOS System Settings.

    Uses ``subprocess.run(["open", SCREEN_RECORDING_PREFS_URL])``.
    If the ``open`` call fails for any reason, logs the error to stderr
    and returns silently without raising.
    """
    try:
        subprocess.run(["open", SCREEN_RECORDING_PREFS_URL], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logging.error("Could not open Screen Recording preferences: %s", exc)


def open_folder(path: pathlib.Path) -> None:
    """Open *path* in macOS Finder.

    Uses ``subprocess.run(["open", str(path)], check=True)``. On
    :class:`subprocess.CalledProcessError` or :class:`FileNotFoundError`,
    logs the error to stderr and returns without re-raising (non-critical
    failure — the app continues to function normally).

    Args:
        path: Directory to open in Finder.
    """
    try:
        subprocess.run(["open", str(path)], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        logging.error("Could not open folder '%s' in Finder: %s", path, exc)

