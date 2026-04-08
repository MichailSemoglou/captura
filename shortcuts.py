"""
shortcuts.py — Keyboard Shortcut Registration (v1.0.0)
=====================================================
Responsibility (spec.md §4, §7):
  Bind and unbind Cmd+1 through Cmd+9 keyboard shortcuts on the
  application's root tkinter window using bind_all, so shortcuts fire
  whenever the app window has keyboard focus regardless of which inner
  widget is currently focused.

Public API:
  SHORTCUT_MAP : dict[str, str]
      Maps each tkinter binding (e.g. ``"<Command-1>"``) to its mode key
      (e.g. ``"fullscreen"``).

  register_shortcuts(
      root:      tkinter.Misc,
      callbacks: dict[str, Callable[[], None]],
  ) -> None
      Bind each Cmd+N shortcut to the matching callback from *callbacks*.
      Mode keys not present in *callbacks* are silently skipped.

  release_shortcuts(root: tkinter.Misc) -> None
      Remove all Cmd+1–9 bindings from root (e.g., on teardown).

v1.0 scope note (spec.md §7):
  Shortcuts are window-focused only (active when the app has focus).
  System-global shortcuts require `pynput` + macOS Accessibility permission
  and are deferred to v1.1.
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable

# Maps tkinter binding → mode key (doubles as the filename suffix).
# NOTE: <Command-Key-N> is the correct form for "Command + keyboard digit N".
#       <Command-N> would bind to "Command + mouse button N", which never
#       fires on real keyboard input — a silent but critical distinction in Tk.
SHORTCUT_MAP: dict[str, str] = {
    "<Command-Key-1>": "fullscreen",
    "<Command-Key-2>": "16x9",
    "<Command-Key-3>": "4x3",
    "<Command-Key-4>": "1x1",
    "<Command-Key-5>": "9x16",
    "<Command-Key-6>": "3x4",
    "<Command-Key-7>": "2x3",
    "<Command-Key-8>": "3x2",
    "<Command-Key-9>": "custom",
}


def register_shortcuts(
    root: tkinter.Misc,
    callbacks: dict[str, Callable[[], None]],
) -> None:
    """Bind Cmd+1 through Cmd+9 to the matching callbacks on *root*.

    Only shortcuts whose mode key appears in *callbacks* are registered;
    unrecognised keys are silently skipped.

    Uses ``bind_all`` so shortcuts fire whenever the application window has
    keyboard focus, regardless of which inner widget is focused.

    Args:
        root:      Root window or any tkinter widget to bind on.
        callbacks: Mapping of mode key → zero-argument callable, e.g.
                   ``{"fullscreen": fn1, "16x9": fn2, ...}``.
    """
    for binding, mode_key in SHORTCUT_MAP.items():
        if mode_key in callbacks:
            fn = callbacks[mode_key]
            root.bind_all(binding, lambda event, f=fn: f())


def release_shortcuts(root: tkinter.Misc) -> None:
    """Remove all Cmd+1–9 ``bind_all`` bindings from *root*.

    Should be called on application teardown to clean up event bindings.

    Args:
        root: The same root widget passed to :func:`register_shortcuts`.
    """
    for binding in SHORTCUT_MAP:
        root.unbind_all(binding)

