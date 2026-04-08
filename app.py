"""
app.py — Application Entry Point & Window Controller (v1.0.0)
============================================================
Responsibility (spec.md §4, §6):
  - Instantiate and configure the CustomTkinter root window (CTk).
  - Build and lay out all UI widgets: preview canvas, 9 capture buttons
    arranged in a 3×3 grid, "Open Screenshots Folder" button, status bar.
  - Wire button click handlers and Cmd+1–9 keyboard shortcuts.
  - For Cmd+9 (custom region): present a full-screen transparent overlay
    (_RegionOverlay) and route the confirmed bounding box to capture.py.
  - Receive capture results from the worker thread and delegate:
      • Preview update  → preview.fit_image_to_canvas()
      • Status update   → CTkLabel.configure(text=…)
  - Detect Screen Recording permission on startup via platform_utils.py
    and show a permission-request dialog if absent.

Public API:
  main() -> None   — entry point; called by main.py.

Threading model:
  Screenshot captures run on a daemon thread.  All GUI mutations are
  routed back to the main thread via root.after(0, callback).

See also:
  capture.py        — screen capture logic (9 modes)
  storage.py        — filename generation and file save
  preview.py        — image resize for canvas display
  shortcuts.py      — Cmd+1–9 keyboard binding
  platform_utils.py — macOS permission check and folder open
"""

from __future__ import annotations

import functools
import logging
import pathlib
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime

import customtkinter as ctk
import mss
from PIL import Image, ImageDraw, ImageTk

import beautify
import capture
import platform_utils
import preview
import shortcuts
import storage
from capture import ScreenCaptureError
from storage import StorageError

_log = logging.getLogger(__name__)

_STATUS_READY = "Ready. Press Cmd+1–9 to capture."

# ---------------------------------------------------------------------------
# Capture mode definitions
# ---------------------------------------------------------------------------

# (mode_key, button_label) in left→right, top→bottom grid order.
_MODES: list[tuple[str, str]] = [
    ("fullscreen", "Fullscreen\nCmd+1"),
    ("16x9",       "16:9 Center Crop\nCmd+2"),
    ("4x3",        "4:3 Center Crop\nCmd+3"),
    ("1x1",        "1:1 Square\nCmd+4"),
    ("9x16",       "9:16 Center Crop\nCmd+5"),
    ("3x4",        "3:4 Center Crop\nCmd+6"),
    ("2x3",        "2:3 Center Crop\nCmd+7"),
    ("3x2",        "3:2 Center Crop\nCmd+8"),
    ("custom",     "Custom Region\nCmd+9"),
]

# Aspect ratio (rw, rh) for each center-crop mode.
_CROP_RATIOS: dict[str, tuple[int, int]] = {
    "16x9": (16, 9),
    "4x3":  (4, 3),
    "1x1":  (1, 1),
    "9x16": (9, 16),
    "3x4":  (3, 4),
    "2x3":  (2, 3),
    "3x2":  (3, 2),
}


# ---------------------------------------------------------------------------
# Permission dialog
# ---------------------------------------------------------------------------

def _show_permission_dialog(root: ctk.CTk) -> None:
    """Display a non-blocking dialog prompting for Screen Recording permission."""
    dialog = ctk.CTkToplevel(root)
    dialog.title("Screen Recording Permission Required")
    dialog.resizable(False, False)

    msg = ctk.CTkLabel(
        dialog,
        text=(
            "Screen Recording permission is required to capture screenshots.\n\n"
            "Click 'Open Privacy Settings', enable this app in\n"
            "System Settings → Privacy & Security → Screen Recording,\n"
            "then relaunch Captura."
        ),
        wraplength=380,
        justify="left",
    )
    msg.pack(padx=24, pady=(24, 12))

    def _open_settings() -> None:
        platform_utils.prompt_screen_recording_permission()
        dialog.destroy()

    ctk.CTkButton(
        dialog,
        text="Open Privacy Settings",
        fg_color="#ffffff",
        text_color="#000000",
        hover_color="#e5e5e5",
        corner_radius=50,
        command=_open_settings,
    ).pack(padx=24, pady=(0, 8), fill="x")

    ctk.CTkButton(
        dialog,
        text="Close",
        fg_color="#262626",
        text_color="#e5e5e5",
        hover_color="#404040",
        corner_radius=50,
        command=dialog.destroy,
    ).pack(padx=24, pady=(0, 24), fill="x")

    # Center over the main window once geometry is known.
    dialog.update_idletasks()
    dx = root.winfo_x() + (root.winfo_width() - dialog.winfo_width()) // 2
    dy = root.winfo_y() + (root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(dx, 0)}+{max(dy, 0)}")
    dialog.lift()


# ---------------------------------------------------------------------------
# Custom region selection overlay (Cmd+9)
# ---------------------------------------------------------------------------

class _RegionOverlay:
    """Full-screen overlay for user-defined region capture.

    Displays a screenshot of the current screen as the background.  The
    user clicks and drags to draw a selection rectangle.  The area outside
    the selection is dimmed while the selected region remains clear.

    After the initial draw the selection can be **moved** (drag inside it)
    and **resized** (drag one of the 8 edge / corner handles).  Press
    **Enter** to confirm or **Escape** to cancel.

    The overlay is always **destroyed** (never withdrawn) before any mss
    capture so it does not appear in the screenshot.
    """

    _MIN_SELECTION = 10
    _HANDLE_SIZE = 8        # half-width of a resize handle
    _DIM_OPACITY = 191      # 0–255; 191 ≈ 75 % black

    def __init__(
        self,
        parent: ctk.CTk,
        on_confirm: Callable[[dict[str, int]], None],
        on_cancel: Callable[[str], None],
    ) -> None:
        self._on_confirm_cb = on_confirm
        self._on_cancel_cb = on_cancel
        self._start_x = 0
        self._start_y = 0
        self._cur_x = 0
        self._cur_y = 0
        self._rect_id: int | None = None
        self._dim_ids: list[int] = []
        self._dim_photos: list[ImageTk.PhotoImage] = []
        self._handle_ids: list[int] = []
        self._dim_id: int | None = None       
        self._hint_ids: list[int] = []
        self._done = False
        self._has_selection = False            
        self._dragging_mode: str | None = None 
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        self._sw = sw
        self._sh = sh

        # Capture a background image of the screen for the overlay.
        try:
            with mss.mss() as sct:
                raw = sct.grab(sct.monitors[1])
                bg_img = Image.frombytes("RGB", raw.size, raw.rgb)
            # Downscale physical → logical if Retina.
            if bg_img.width != sw or bg_img.height != sh:
                bg_img = bg_img.resize((sw, sh), Image.Resampling.LANCZOS)
            self._bg_photo = ImageTk.PhotoImage(bg_img)
        except Exception:
            # Fallback: plain black background.
            self._bg_photo = None

        # Build the overlay window.
        self._win = tk.Toplevel(parent)
        self._win.withdraw()
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.geometry(f"{sw}x{sh}+0+0")
        self._win.configure(bg="black")

        # Full-screen canvas.
        self._canvas = tk.Canvas(
            self._win,
            bg="black",
            cursor="crosshair",
            highlightthickness=0,
        )
        self._canvas.place(x=0, y=0, width=sw, height=sh)

        # Place the background image on the canvas.
        if self._bg_photo is not None:
            self._canvas.create_image(0, 0, anchor="nw", image=self._bg_photo)

        # Draw initial full-screen dim overlay.
        self._draw_dim_mask(0, 0, 0, 0)

        # Instruction hint.
        hint = self._canvas.create_text(
            sw // 2,
            sh // 2,
            text="Click and drag to select a region.\n"
                 "Enter to capture  ·  Escape to cancel",
            fill="#ffffff",
            font=("Helvetica", 16),
            justify="center",
        )
        self._hint_ids.append(hint)

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Return>", self._on_enter)
        self._win.bind("<Escape>", self._on_escape)
        self._canvas.bind("<Return>", self._on_enter)
        self._canvas.bind("<Escape>", self._on_escape)

        self._win.deiconify()
        self._win.lift()
        self._win.focus_force()
        self._canvas.focus_set()

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _clamp(self, x: int, y: int) -> tuple[int, int]:
        """Clamp (x, y) to stay within the overlay bounds."""
        return max(0, min(x, self._sw)), max(0, min(y, self._sh))

    def _draw_dim_mask(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Draw a semi-transparent black overlay around the selection,
        leaving the selected area clear.  Uses PIL RGBA compositing for
        true alpha transparency.
        """
        for item_id in self._dim_ids:
            self._canvas.delete(item_id)
        self._dim_ids.clear()
        # Release previous dim photo references.
        self._dim_photos.clear()

        sw, sh = self._sw, self._sh
        alpha = self._DIM_OPACITY

        # (x, y, w, h) for the four strips around the selection.
        strips = [
            (0, 0, sw, y1),          # top
            (0, y2, sw, sh - y2),    # bottom
            (0, y1, x1, y2 - y1),   # left
            (x2, y1, sw - x2, y2 - y1),  # right
        ]
        for sx, sy, sw_s, sh_s in strips:
            if sw_s <= 0 or sh_s <= 0:
                continue
            img = Image.new("RGBA", (sw_s, sh_s), (0, 0, 0, alpha))
            photo = ImageTk.PhotoImage(img)
            self._dim_photos.append(photo)
            self._dim_ids.append(
                self._canvas.create_image(sx, sy, anchor="nw", image=photo)
            )

    def _draw_handles(self, x1: int, y1: int, x2: int, y2: int) -> None:
        """Draw 8 resize handles around the selection border."""
        for item_id in self._handle_ids:
            self._canvas.delete(item_id)
        self._handle_ids.clear()

        hs = self._HANDLE_SIZE
        mx = (x1 + x2) // 2
        my = (y1 + y2) // 2

        # (centre_x, centre_y, cursor, tag)
        positions = [
            (x1, y1, "top_left_corner",     "h_tl"),
            (x2, y1, "top_right_corner",    "h_tr"),
            (x1, y2, "bottom_left_corner",  "h_bl"),
            (x2, y2, "bottom_right_corner", "h_br"),
            (mx, y1, "sb_v_double_arrow",   "h_t"),
            (mx, y2, "sb_v_double_arrow",   "h_b"),
            (x1, my, "sb_h_double_arrow",   "h_l"),
            (x2, my, "sb_h_double_arrow",   "h_r"),
        ]
        for cx, cy, cursor, tag in positions:
            hid = self._canvas.create_rectangle(
                cx - hs, cy - hs, cx + hs, cy + hs,
                fill="#ffffff", outline="#333333", width=1, tags=(tag,)
            )
            self._handle_ids.append(hid)

    def _redraw_selection(self) -> None:
        """Redraw the selection rectangle, dim mask, handles, and dimension label."""
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
        if self._dim_id is not None:
            self._canvas.delete(self._dim_id)

        x1 = min(self._start_x, self._cur_x)
        y1 = min(self._start_y, self._cur_y)
        x2 = max(self._start_x, self._cur_x)
        y2 = max(self._start_y, self._cur_y)

        self._draw_dim_mask(x1, y1, x2, y2)

        self._rect_id = self._canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#ffffff",
            width=2,
        )
        w = x2 - x1
        h = y2 - y1
        label_y = y1 - 20 if y1 > 30 else y2 + 6
        self._dim_id = self._canvas.create_text(
            x1,
            label_y,
            text=f"  {w} × {h}",
            fill="#ffffff",
            anchor="nw",
            font=("Helvetica", 12, "bold"),
        )

        if self._has_selection:
            self._draw_handles(x1, y1, x2, y2)

    def _selection_bbox(self) -> tuple[int, int, int, int]:
        """Return (x1, y1, x2, y2) of the current selection."""
        x1 = min(self._start_x, self._cur_x)
        y1 = min(self._start_y, self._cur_y)
        x2 = max(self._start_x, self._cur_x)
        y2 = max(self._start_y, self._cur_y)
        return x1, y1, x2, y2

    def _hit_test(self, ex: int, ey: int) -> str | None:
        """Return the interaction target at (ex, ey).

        Returns a handle tag (``"h_tl"``, ``"h_br"``, etc.), ``"move"`` if
        inside the selection, or ``None`` if outside.
        """
        hs = self._HANDLE_SIZE + 2
        x1, y1, x2, y2 = self._selection_bbox()
        mx = (x1 + x2) // 2
        my = (y1 + y2) // 2

        positions = [
            ("h_tl", x1, y1), ("h_tr", x2, y1),
            ("h_bl", x1, y2), ("h_br", x2, y2),
            ("h_t", mx, y1),  ("h_b", mx, y2),
            ("h_l", x1, my),  ("h_r", x2, my),
        ]
        for tag, cx, cy in positions:
            if abs(ex - cx) <= hs and abs(ey - cy) <= hs:
                return tag

        if x1 <= ex <= x2 and y1 <= ey <= y2:
            return "move"
        return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_press(self, event: tk.Event) -> None:
        """Begin a draw, move, or resize operation."""
        self._canvas.focus_set()
        for item_id in self._hint_ids:
            self._canvas.delete(item_id)
        self._hint_ids.clear()

        if self._has_selection:
            target = self._hit_test(event.x, event.y)
            if target == "move":
                self._dragging_mode = "move"
                x1, y1, _, _ = self._selection_bbox()
                self._drag_offset_x = event.x - x1
                self._drag_offset_y = event.y - y1
                return
            if target is not None and target.startswith("h_"):
                self._dragging_mode = target
                return
            # Click outside selection: start a new selection.

        self._dragging_mode = "draw"
        self._has_selection = False
        self._start_x = event.x
        self._start_y = event.y
        self._cur_x = event.x
        self._cur_y = event.y

    def _on_drag(self, event: tk.Event) -> None:
        """Handle draw, move, or resize drag."""
        ex, ey = self._clamp(event.x, event.y)

        if self._dragging_mode == "draw":
            self._cur_x, self._cur_y = ex, ey
            self._redraw_selection()
            return

        if self._dragging_mode == "move":
            x1, y1, x2, y2 = self._selection_bbox()
            w, h = x2 - x1, y2 - y1
            nx = ex - self._drag_offset_x
            ny = ey - self._drag_offset_y
            # Constrain to screen bounds.
            nx = max(0, min(nx, self._sw - w))
            ny = max(0, min(ny, self._sh - h))
            self._start_x, self._start_y = nx, ny
            self._cur_x, self._cur_y = nx + w, ny + h
            self._redraw_selection()
            return

        if self._dragging_mode and self._dragging_mode.startswith("h_"):
            x1, y1, x2, y2 = self._selection_bbox()
            tag = self._dragging_mode
            if "l" in tag:
                x1 = ex
            if "r" in tag:
                x2 = ex
            if "t" in tag:
                y1 = ey
            if "b" in tag:
                y2 = ey
            # Normalise so start < cur.
            self._start_x = min(x1, x2)
            self._start_y = min(y1, y2)
            self._cur_x = max(x1, x2)
            self._cur_y = max(y1, y2)
            self._redraw_selection()

    def _on_release(self, event: tk.Event) -> None:
        """Finalize the draw / adjust operation; enable handles."""
        if self._dragging_mode == "draw":
            ex, ey = self._clamp(event.x, event.y)
            self._cur_x, self._cur_y = ex, ey
        self._dragging_mode = None
        x1, y1, x2, y2 = self._selection_bbox()
        if abs(x2 - x1) >= self._MIN_SELECTION and abs(y2 - y1) >= self._MIN_SELECTION:
            self._has_selection = True
        self._redraw_selection()
        self._canvas.focus_set()

    def _on_enter(self, event: tk.Event = None) -> None:
        """Confirm the current selection and call *on_confirm* or *on_cancel*."""
        if self._done:
            return
        self._done = True
        x1, y1, x2, y2 = self._selection_bbox()
        width = x2 - x1
        height = y2 - y1
        self._win.destroy()
        if width < self._MIN_SELECTION or height < self._MIN_SELECTION:
            self._on_cancel_cb("Selection too small. Try again.")
        else:
            self._on_confirm_cb(
                {"left": x1, "top": y1, "width": width, "height": height}
            )

    def _on_escape(self, event: tk.Event = None) -> None:
        """Cancel without capturing."""
        if self._done:
            return
        self._done = True
        self._win.destroy()
        self._on_cancel_cb("Cancelled.")


# ---------------------------------------------------------------------------
# Post-capture beautification panel
# ---------------------------------------------------------------------------

class _BeautifyPanel(ctk.CTkFrame):
    """Post-capture styling panel (embedded in the main window).

    Presents background, padding, corner-radius, and shadow controls with a
    live preview.  The user saves the styled image, saves the raw original,
    or discards the capture without saving.
    """

    _PREVIEW_MAX: int = 460
    _SHADOW_KEYS: tuple[str, ...] = ("none", "small", "medium", "large")

    def __init__(
        self,
        parent: "App",
        raw_image: Image.Image,
        mode_key: str,
    ) -> None:
        super().__init__(parent, fg_color="#090909", corner_radius=0)
        self._parent = parent
        self._raw = raw_image
        self._mode_key = mode_key
        self._settings = beautify.BeautifySettings()
        self._pending: str | None = None

        # Strong references so PhotoImages are not garbage-collected.
        self._swatch_photos: list[ImageTk.PhotoImage] = []
        self._solid_photos: list[ImageTk.PhotoImage] = []
        self._swatch_btns: list[tk.Button] = []
        self._solid_btns: list[tk.Button] = []

        # Downsample for fast live-preview rendering.
        w, h = raw_image.size
        scale = min(self._PREVIEW_MAX / w, self._PREVIEW_MAX / h, 1.0)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        self._thumb = raw_image.resize((nw, nh), Image.Resampling.LANCZOS)

        self._build_ui()
        self._highlight_gradient(0)

        # Delay the first preview until after the canvas has been mapped.
        self.after(60, self._update_preview)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _make_gradient_swatch(
        self,
        c1: tuple[int, int, int],
        c2: tuple[int, int, int],
    ) -> ImageTk.PhotoImage:
        """Return a small (44×28) gradient PhotoImage for use as a swatch."""
        img = Image.new("RGB", (44, 28))
        draw = ImageDraw.Draw(img)
        for x in range(44):
            t = x / 43
            r = round(c1[0] + (c2[0] - c1[0]) * t)
            g = round(c1[1] + (c2[1] - c1[1]) * t)
            b = round(c1[2] + (c2[2] - c1[2]) * t)
            draw.line([(x, 0), (x, 27)], fill=(r, g, b))
        return ImageTk.PhotoImage(img)

    def _build_ui(self) -> None:
        """Construct all widgets and lay them out."""
        self.grid_columnconfigure(0, minsize=250, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # ── Left column: controls ─────────────────────────────────────
        left = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 4), pady=(12, 4))
        left.grid_propagate(False)

        def _section(text: str, pady_top: int = 8) -> None:
            ctk.CTkLabel(
                left, text=text, font=ctk.CTkFont(size=12, weight="bold")
            ).pack(anchor="w", pady=(pady_top, 2))

        # Gradient swatches — 2 rows of 4.
        _section("Background", pady_top=0)
        for row_start in (0, 4):
            row_frame = ctk.CTkFrame(left, fg_color="transparent")
            row_frame.pack(anchor="w", pady=2)
            for i in range(row_start, row_start + 4):
                c1, c2 = beautify.GRADIENTS[i]
                photo = self._make_gradient_swatch(c1, c2)
                self._swatch_photos.append(photo)
                btn = tk.Button(
                    row_frame,
                    image=photo,
                    relief="flat",
                    bd=0,
                    bg="#090909",
                    activebackground="#111111",
                    cursor="hand2",
                    highlightthickness=2,
                    highlightbackground="#404040",
                    padx=0,
                    pady=0,
                    command=lambda idx=i: self._on_gradient_select(idx),
                )
                btn.pack(side="left", padx=3)
                self._swatch_btns.append(btn)

        # Solid colour swatches.
        _section("Solid Background")
        solid_row = ctk.CTkFrame(left, fg_color="transparent")
        solid_row.pack(anchor="w", pady=2)
        for i, color in enumerate(beautify.SOLID_COLORS):
            photo = ImageTk.PhotoImage(Image.new("RGB", (44, 28), color))
            self._solid_photos.append(photo)
            btn = tk.Button(
                solid_row,
                image=photo,
                relief="flat",
                bd=0,
                bg="#090909",
                activebackground="#111111",
                cursor="hand2",
                highlightthickness=2,
                highlightbackground="#404040",
                padx=0,
                pady=0,
                command=lambda c=color: self._on_solid_select(c),
            )
            btn.pack(side="left", padx=3)
            self._solid_btns.append(btn)

        # Padding slider.
        _section("Padding")
        self._pad_slider = ctk.CTkSlider(
            left, from_=0, to=120, number_of_steps=30,
            width=220,
            button_color="#808080",
            button_hover_color="#a0a0a0",
            progress_color="#606060",
            fg_color="#333333",
            command=self._on_padding_change,
        )
        self._pad_slider.set(self._settings.padding)
        self._pad_slider.pack(anchor="w", pady=(1, 0))
        self._pad_label = ctk.CTkLabel(
            left, text=f"{self._settings.padding}px", anchor="w",
            font=ctk.CTkFont(size=11), text_color="#808080"
        )
        self._pad_label.pack(anchor="w", pady=(0, 6))

        # Rounded corners slider.
        _section("Rounded Corners")
        self._corner_slider = ctk.CTkSlider(
            left, from_=0, to=60, number_of_steps=30,
            width=220,
            button_color="#808080",
            button_hover_color="#a0a0a0",
            progress_color="#606060",
            fg_color="#333333",
            command=self._on_corner_change,
        )
        self._corner_slider.set(self._settings.corner_radius)
        self._corner_slider.pack(anchor="w", pady=(1, 0))
        self._corner_label = ctk.CTkLabel(
            left, text=f"{self._settings.corner_radius}px", anchor="w",
            font=ctk.CTkFont(size=11), text_color="#808080"
        )
        self._corner_label.pack(anchor="w", pady=(0, 6))

        # Shadow slider.
        _section("Shadow")
        self._shadow_slider = ctk.CTkSlider(
            left, from_=0, to=3, number_of_steps=3,
            width=220,
            button_color="#808080",
            button_hover_color="#a0a0a0",
            progress_color="#606060",
            fg_color="#333333",
            command=self._on_shadow_change,
        )
        _sz = self._settings.shadow_size
        _shadow_idx = self._SHADOW_KEYS.index(_sz) if _sz in self._SHADOW_KEYS else 2
        self._shadow_slider.set(_shadow_idx)
        self._shadow_slider.pack(anchor="w", pady=(1, 0))
        self._shadow_label = ctk.CTkLabel(
            left, text=self._settings.shadow_size.capitalize(), anchor="w",
            font=ctk.CTkFont(size=11), text_color="#808080"
        )
        self._shadow_label.pack(anchor="w", pady=(0, 6))

        # ── Right column: live preview canvas ─────────────────────────
        self._preview_canvas = tk.Canvas(
            self, bg="#090909", highlightthickness=0
        )
        self._preview_canvas.grid(
            row=0, column=1, sticky="nsew", padx=(4, 12), pady=(12, 4)
        )

        # ── Bottom row: action buttons spanning both columns ──────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(
            btn_row,
            text="Save Styled",
            fg_color="#ffffff",
            text_color="#000000",
            hover_color="#e5e5e5",
            corner_radius=50,
            command=self._on_save_beautified,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            btn_row,
            text="Save Original",
            fg_color="#262626",
            text_color="#e5e5e5",
            hover_color="#404040",
            corner_radius=50,
            command=self._on_save_original,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            btn_row,
            text="Discard",
            fg_color="#090909",
            text_color="#a3a3a3",
            hover_color="#111111",
            border_width=1,
            border_color="#404040",
            corner_radius=50,
            command=self._on_discard,
        ).grid(row=0, column=2, sticky="ew")

    # ------------------------------------------------------------------
    # Swatch selection highlighting
    # ------------------------------------------------------------------

    def _highlight_gradient(self, idx: int) -> None:
        """Highlight the *idx*-th gradient swatch and clear all solid highlights."""
        for i, btn in enumerate(self._swatch_btns):
            btn.config(
                highlightbackground="#ffffff" if i == idx else "#404040"
            )
        for btn in self._solid_btns:
            btn.config(highlightbackground="#404040")

    def _highlight_solid(self, color: tuple[int, int, int]) -> None:
        """Highlight the solid swatch matching *color* and clear gradient highlights."""
        for btn in self._swatch_btns:
            btn.config(highlightbackground="#404040")
        for btn, c in zip(self._solid_btns, beautify.SOLID_COLORS):
            btn.config(highlightbackground="#ffffff" if c == color else "#404040")

    # ------------------------------------------------------------------
    # Control event handlers
    # ------------------------------------------------------------------

    def _on_gradient_select(self, idx: int) -> None:
        self._settings.bg_type = "gradient"
        self._settings.gradient_index = idx
        self._highlight_gradient(idx)
        self._schedule_preview_update()

    def _on_solid_select(self, color: tuple[int, int, int]) -> None:
        self._settings.bg_type = "solid"
        self._settings.bg_color = color
        self._highlight_solid(color)
        self._schedule_preview_update()

    def _on_padding_change(self, value: float) -> None:
        self._settings.padding = int(value)
        self._pad_label.configure(text=f"{int(value)}px")
        self._schedule_preview_update()

    def _on_corner_change(self, value: float) -> None:
        self._settings.corner_radius = int(value)
        self._corner_label.configure(text=f"{int(value)}px")
        self._schedule_preview_update()

    def _on_shadow_change(self, value: float) -> None:
        label = self._SHADOW_KEYS[int(round(value))]
        self._settings.shadow_size = label
        self._shadow_label.configure(text=label.capitalize())
        self._schedule_preview_update()

    # ------------------------------------------------------------------
    # Live preview
    # ------------------------------------------------------------------

    def _schedule_preview_update(self) -> None:
        """Debounce preview updates: wait 120 ms of idle before refreshing."""
        if self._pending:
            self.after_cancel(self._pending)
        self._pending = self.after(120, self._update_preview)

    def _update_preview(self) -> None:
        """Apply beautification to the thumbnail and render in the preview canvas."""
        self._pending = None
        try:
            beautified = beautify.apply_beautification(self._thumb, self._settings)
        except Exception as exc:
            _log.error("Beautify preview error: %s", exc)
            return
        cw = self._preview_canvas.winfo_width()
        ch = self._preview_canvas.winfo_height()
        if cw < 4 or ch < 4:
            return
        fitted = preview.fit_image_to_canvas(beautified, cw, ch)
        photo = ImageTk.PhotoImage(fitted)
        self._preview_canvas.delete("all")
        self._preview_canvas.create_image(
            cw // 2, ch // 2, anchor="center", image=photo
        )
        self._preview_canvas._photo_ref = photo

    # ------------------------------------------------------------------
    # Save / discard
    # ------------------------------------------------------------------

    def _save(self, image: Image.Image) -> None:
        """Save *image* to disk and notify the parent window."""
        try:
            filename = storage.generate_filename(datetime.now(), self._mode_key)
            directory = storage.get_screenshots_dir()
            saved_path = storage.save_image(image, directory, filename)
            _log.info("Beautify save: %s", saved_path)
            self._parent._finish_beautify_save(image, saved_path)
        except StorageError as exc:
            _log.error("Storage error in beautify panel: %s", exc)
            self._parent._finish_beautify_error(str(exc))

    def _on_save_beautified(self) -> None:
        """Apply full-resolution styling and save."""
        try:
            final = beautify.apply_beautification(self._raw, self._settings)
        except Exception as exc:
            _log.error("Beautify full-res error: %s", exc)
            self._parent._finish_beautify_error(f"Beautify error: {exc}")
            return
        self._save(final)

    def _on_save_original(self) -> None:
        """Save the raw (unstyled) screenshot."""
        self._save(self._raw)

    def _on_discard(self) -> None:
        """Discard the capture without saving."""
        self._parent._finish_beautify_discard()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    """Main application window for Captura v1.0.0 (spec.md §6)."""

    def __init__(self) -> None:
        super().__init__()

        self.title("Captura")
        self.geometry("700x720")
        self.minsize(600, 560)
        self.configure(fg_color="#090909")

        # Pre-warm the display-info cache on the main thread so that
        # background capture threads only read the already-cached value
        # and never touch tkinter from a non-main thread.
        capture.warm_display_cache()

        # Last captured image; None when no capture has been made yet.
        self._current_image: Image.Image | None = None
        self._capturing: bool = False
        self._beautify_panel: _BeautifyPanel | None = None

        # Populated by _build_ui(): mode_key → CTkButton
        self._capture_buttons: dict[str, ctk.CTkButton] = {}

        self._build_ui()

        # Register Cmd+1–9 shortcuts.
        shortcuts.register_shortcuts(
            self,
            {mode_key: (lambda mk=mode_key: self._on_capture_mode(mk))
             for mode_key, _ in _MODES},
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._check_permission)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build and grid all widgets per spec.md §6 layout (v1.0.0)."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)   # content area
        self.grid_rowconfigure(1, weight=0)   # status bar

        # ── Capture-mode frame (row 0) ────────────────────────────────
        self._capture_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._capture_frame.grid(row=0, column=0, sticky="nsew")
        self._capture_frame.grid_columnconfigure(0, weight=1)
        self._capture_frame.grid_rowconfigure(0, weight=1)

        # Preview canvas.
        self._canvas = tk.Canvas(
            self._capture_frame, bg="#111111", highlightthickness=0, bd=0
        )
        self._canvas.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 8))
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # 3×3 button grid.
        btn_frame = ctk.CTkFrame(self._capture_frame, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for col in range(3):
            btn_frame.grid_columnconfigure(col, weight=1)

        for idx, (mode_key, label) in enumerate(_MODES):
            row = idx // 3
            col = idx % 3
            btn = ctk.CTkButton(
                btn_frame,
                text=label,
                height=56,
                command=lambda mk=mode_key: self._on_capture_mode(mk),
                font=ctk.CTkFont(size=12),
                fg_color="#262626",
                text_color="#e5e5e5",
                hover_color="#404040",
                border_width=1,
                border_color="#262626",
                corner_radius=50,
            )
            btn.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            self._capture_buttons[mode_key] = btn

        # Open Screenshots Folder button.
        self._btn_open_folder = ctk.CTkButton(
            self._capture_frame,
            text="Open Screenshots Folder",
            fg_color="#090909",
            text_color="#a3a3a3",
            hover_color="#111111",
            border_width=1,
            border_color="#404040",
            corner_radius=50,
            command=self._on_open_folder,
        )
        self._btn_open_folder.grid(row=2, column=0, padx=12, pady=4, sticky="ew")

        # ── Status bar (row 1 of App, always visible) ─────────────────
        self._status_label = ctk.CTkLabel(
            self,
            text=_STATUS_READY,
            anchor="w",
            justify="left",
            font=ctk.CTkFont(family="Menlo", size=11),
            text_color="#737373",
            wraplength=650,
        )
        self._status_label.grid(
            row=1, column=0, padx=12, pady=(4, 12), sticky="ew"
        )

        # Keep wraplength in sync with window width.
        self.bind("<Configure>", self._on_window_resize)

    # ------------------------------------------------------------------
    # Canvas rendering
    # ------------------------------------------------------------------

    def _draw_placeholder(
        self, width: int | None = None, height: int | None = None
    ) -> None:
        """Draw the 'No screenshot captured yet' placeholder text."""
        w = width or self._canvas.winfo_width() or 676
        h = height or self._canvas.winfo_height() or 400
        self._canvas.delete("all")
        self._canvas.create_text(
            w // 2,
            h // 2,
            text="No screenshot captured yet",
            fill="#525252",
            font=("Helvetica", 14),
        )

    def _on_canvas_resize(self, event: tk.Event) -> None:
        """Redraw image (or placeholder) whenever the canvas changes dimensions."""
        if self._current_image is None:
            self._draw_placeholder(event.width, event.height)
        else:
            self._render_image(self._current_image)

    def _on_window_resize(self, event: tk.Event) -> None:
        """Keep the status bar wraplength in sync with the window width."""
        if event.widget is self:
            self._status_label.configure(wraplength=max(event.width - 24, 100))

    def _render_image(self, pil_image: Image.Image) -> None:
        """Scale *pil_image* to fit the canvas and display it centred."""
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 2 or h < 2:
            return

        fitted = preview.fit_image_to_canvas(pil_image, w, h)
        photo = ImageTk.PhotoImage(fitted)
        self._canvas.delete("all")
        self._canvas.create_image(w // 2, h // 2, anchor="center", image=photo)
        # Keep a strong reference so the PhotoImage is not garbage-collected.
        self._canvas._photo_ref = photo

    # ------------------------------------------------------------------
    # Capture mode dispatch
    # ------------------------------------------------------------------

    def _on_capture_mode(self, mode_key: str) -> None:
        """Entry point for all capture shortcuts and button clicks.

        Routes to the custom-region overlay for ``"custom"``, or starts a
        background capture for all other modes.  No-ops if a capture is
        already in progress.

        Args:
            mode_key: One of the mode keys in :data:`_MODES`.
        """
        if self._capturing:
            return
        if mode_key == "custom":
            self._start_custom_region()
            return
        self._flash_button(self._capture_buttons[mode_key])
        if mode_key == "fullscreen":
            capture_fn: Callable[[], Image.Image] = capture.capture_fullscreen
        else:
            ratio = _CROP_RATIOS[mode_key]
            capture_fn = functools.partial(capture.capture_center_crop, ratio)
        self._start_capture(mode_key, capture_fn)

    def _start_custom_region(self) -> None:
        """Open the full-screen overlay for custom region selection (Cmd+9).

        The main window is made invisible via alpha=0 rather than withdrawn
        so the application remains the active macOS process.  This lets the
        overrideredirect overlay receive Return/Escape key events via
        focus_force().  A 150 ms delay gives macOS time to repaint before
        the overlay takes its background screenshot.  Alpha is restored to
        1.0 on cancel (in _on_region_cancelled) or after capture completes
        (in _on_capture_done / _on_error).
        """
        self._capturing = True
        self._disable_capture_buttons()
        self._flash_button(self._capture_buttons["custom"])
        self._status_label.configure(
            text="Drag to select a region. Enter to confirm, Escape to cancel."
        )
        self.attributes("-alpha", 0.0)
        self.after(150, self._show_region_overlay)

    def _show_region_overlay(self) -> None:
        """Create the _RegionOverlay after the window has visually hidden."""
        _RegionOverlay(
            parent=self,
            on_confirm=self._on_region_confirmed,
            on_cancel=self._on_region_cancelled,
        )

    def _on_region_confirmed(self, bbox: dict[str, int]) -> None:
        """Called when the user confirms a region selection.

        Waits 80 ms to ensure the overlay window is fully destroyed before
        calling ``mss.grab()``.
        """
        self.after(
            80,
            lambda: self._start_capture(
                "custom", lambda b=bbox: capture.capture_region(b)
            ),
        )

    def _on_region_cancelled(self, message: str) -> None:
        """Called when the user cancels region selection."""
        self.attributes("-alpha", 1.0)
        self._status_label.configure(text=message)
        self._capturing = False
        self._enable_capture_buttons()

    # ------------------------------------------------------------------
    # Background capture execution
    # ------------------------------------------------------------------

    def _flash_button(self, btn: ctk.CTkButton) -> None:
        """Briefly change the button colour to white as visual feedback."""
        original = btn.cget("fg_color")
        btn.configure(fg_color="#e5e5e5")
        self.after(120, lambda: btn.configure(fg_color=original))

    def _disable_capture_buttons(self) -> None:
        """Disable all nine capture buttons while a capture is in progress."""
        for btn in self._capture_buttons.values():
            btn.configure(state="disabled")

    def _enable_capture_buttons(self) -> None:
        """Re-enable all nine capture buttons after a capture completes."""
        for btn in self._capture_buttons.values():
            btn.configure(state="normal")

    def _start_capture(
        self, mode_key: str, capture_fn: Callable[[], Image.Image]
    ) -> None:
        """Disable UI, show 'Capturing…', and run *capture_fn* on a daemon thread.

        Args:
            mode_key:   Mode key string used as the filename suffix.
            capture_fn: Zero-argument callable that performs the capture.
        """
        self._capturing = True
        self._disable_capture_buttons()
        self._status_label.configure(text="Capturing...")

        def _worker() -> None:
            try:
                pil_image = capture_fn()
                self.after(
                    0,
                    lambda img=pil_image: self._on_capture_done(img, mode_key),
                )
            except ScreenCaptureError as exc:
                _log.error("Capture failed: %s", exc)
                msg = str(exc)
                self.after(0, lambda m=msg: self._on_capture_error(m))
            except Exception as exc:
                _log.error("Unexpected error during capture", exc_info=True)
                msg = f"Unexpected error: {exc}"
                self.after(0, lambda m=msg: self._on_error(m))

        # Hide the window, wait 200 ms for macOS to fully repaint the screen
        # without it, then start the capture thread.
        self.withdraw()
        self.after(200, lambda: threading.Thread(target=_worker, daemon=True).start())

    def _on_capture_done(self, pil_image: Image.Image, mode_key: str) -> None:
        """Main-thread callback: restore the window and show the styling panel."""
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self._capture_frame.grid_forget()
        self._beautify_panel = _BeautifyPanel(
            parent=self, raw_image=pil_image, mode_key=mode_key
        )
        self._beautify_panel.grid(row=0, column=0, sticky="nsew")
        self._status_label.configure(text="Adjust styling, then save or discard.")

    def _dismiss_beautify_panel(self) -> None:
        """Remove the styling panel and restore the capture UI."""
        if self._beautify_panel is not None:
            self._beautify_panel.grid_forget()
            self._beautify_panel.destroy()
            self._beautify_panel = None
        self._capture_frame.grid(row=0, column=0, sticky="nsew")

    def _finish_beautify_save(
        self, pil_image: Image.Image, saved_path: pathlib.Path
    ) -> None:
        """Called by _BeautifyPanel after a successful save."""
        self._dismiss_beautify_panel()
        self._current_image = pil_image
        self._render_image(pil_image)
        self._status_label.configure(text=f"Saved: {saved_path}")
        self._capturing = False
        self._enable_capture_buttons()

    def _finish_beautify_discard(self) -> None:
        """Called by _BeautifyPanel when the user discards."""
        self._dismiss_beautify_panel()
        self._status_label.configure(text=_STATUS_READY)
        self._capturing = False
        self._enable_capture_buttons()

    def _finish_beautify_error(self, message: str) -> None:
        """Called by _BeautifyPanel on error."""
        self._dismiss_beautify_panel()
        self._status_label.configure(text=message)
        self._capturing = False
        self._enable_capture_buttons()

    def _on_capture_error(self, message: str) -> None:
        """Main-thread callback for :class:`~capture.ScreenCaptureError`.

        If the message looks like a permission problem, appends a hint to
        open System Settings rather than showing a raw exception string.
        """
        if "permission" in message.lower() or "screen recording" in message.lower():
            status = (
                "Error: Screen Recording permission required. "
                "Open System Settings → Privacy & Security "
                "→ Screen Recording and enable this app, then relaunch."
            )
            _show_permission_dialog(self)
        else:
            status = f"Error: {message}"
        self._on_error(status)

    def _on_error(self, message: str) -> None:
        """Main-thread callback: show error message and re-enable buttons."""
        self.attributes("-alpha", 1.0)
        self.deiconify()
        self._status_label.configure(text=message)
        self._capturing = False
        self._enable_capture_buttons()

    # ------------------------------------------------------------------
    # Folder button
    # ------------------------------------------------------------------

    def _on_open_folder(self) -> None:
        """Ensure ~/Screenshots exists, then open it in Finder."""
        try:
            directory = storage.get_screenshots_dir()
            platform_utils.open_folder(directory)
            _log.info("Opened screenshots folder: %s", directory)
        except StorageError as exc:
            _log.error("Could not open screenshots folder: %s", exc)
            self._status_label.configure(text=f"Error: {exc}")

    # ------------------------------------------------------------------
    # Startup permission check
    # ------------------------------------------------------------------

    def _check_permission(self) -> None:
        """Show a permission dialog if Screen Recording access is not granted."""
        if not platform_utils.has_screen_recording_permission():
            _show_permission_dialog(self)

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Release shortcuts cleanly, then destroy the window."""
        try:
            shortcuts.release_shortcuts(self)
        except Exception:
            pass
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Configure logging, then launch Captura."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

