"""Small, bounded Canvas animations; the desktop window itself never moves."""

from __future__ import annotations

import math
import time
import tkinter as tk


class PetAnimation:
    FRAME_MS = 50

    def __init__(self, canvas: tk.Canvas, image: tk.PhotoImage):
        self.canvas = canvas
        self.enabled = True
        self._closed = False
        self._held = False
        self._after_id: str | None = None
        self._started = time.monotonic()
        self._clicked: float | None = None
        # Four pixels around the original 64px artwork leave room for the bounce.
        self._body = canvas.create_image(36, 36, image=image)
        # This pose has one visible eye. Draw the eyelid over it, preserving the asset.
        self._lid = canvas.create_rectangle(27, 16, 32, 21, fill="white", outline="")
        self._eye = canvas.create_line(
            28, 18, 29.5, 18.7, 31, 18, fill="#161616", width=1.3, smooth=True
        )
        self._sparkles = [
            canvas.create_line(10, 19, 16, 19, fill="#6590FF", width=1.4),
            canvas.create_line(13, 16, 13, 22, fill="#6590FF", width=1.4),
        ]
        self._hovered = False
        self._draw(0, False)
        self._schedule()

    def _schedule(self) -> None:
        if self.enabled and not self._closed and not self._held and self._after_id is None:
            self._after_id = self.canvas.after(self.FRAME_MS, self._tick)

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.canvas.after_cancel(self._after_id)
            self._after_id = None

    def _draw(self, dy: float, blink: bool) -> None:
        self.canvas.coords(self._body, 36, 36 + dy)
        self.canvas.coords(self._lid, 27, 16 + dy, 32, 21 + dy)
        self.canvas.coords(self._eye, 28, 18 + dy, 29.5, 18.7 + dy, 31, 18 + dy)
        state = "normal" if blink else "hidden"
        self.canvas.itemconfigure(self._lid, state=state)
        self.canvas.itemconfigure(self._eye, state=state)
        for item in self._sparkles:
            self.canvas.itemconfigure(
                item, state="normal" if self.enabled and self._hovered else "hidden"
            )

    def _tick(self) -> None:
        self._after_id = None
        if self._closed or not self.enabled or self._held:
            return
        now = time.monotonic()
        elapsed = now - self._started
        dy = 1.4 * math.sin(elapsed * math.tau / 3.6)
        blink = 3.7 <= elapsed % 5.3 < 3.9
        if self._clicked is not None:
            age = now - self._clicked
            if age < 0.45:
                dy = -3.5 * math.sin(math.pi * age / 0.45)
            else:
                self._clicked = None
                self._started = now  # Resume idle from rest after the greeting.
                dy = 0
        self._draw(dy, blink)
        self._schedule()

    def hover(self, active: bool) -> None:
        if self._closed:
            return
        self._hovered = active
        # Hover only changes the accent, so the mascot cannot dodge the pointer.
        for item in self._sparkles:
            self.canvas.itemconfigure(
                item, state="normal" if self.enabled and active and not self._held else "hidden"
            )

    def hold(self) -> None:
        if self._closed:
            return
        self._held = True
        self._clicked = None
        self._cancel()
        # Freeze the current pose while a button or context menu owns the pointer.
        for item in self._sparkles:
            self.canvas.itemconfigure(item, state="hidden")

    def release(self, *, clicked: bool = False) -> None:
        if self._closed:
            return
        self._held = False
        self._started = time.monotonic()
        self._clicked = self._started if clicked and self.enabled else None
        if not self.enabled:
            self._draw(0, False)
        self._schedule()

    def set_enabled(self, enabled: bool) -> None:
        if self._closed:
            return
        self.enabled = enabled
        self._clicked = None
        self._started = time.monotonic()
        self._cancel()
        self._draw(0, False)
        self._schedule()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel()
