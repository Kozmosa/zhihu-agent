"""The mascot owns Tk; the compact assistant uses a separate WebView process."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any

import httpx

from zhijing.desktop_animation import PetAnimation
from zhijing.desktop_panel import PanelController
from zhijing.desktop_service import DesktopServiceError


class DesktopAssistant:
    def __init__(self, service: Any):
        self.service = service
        self.panel = PanelController(service.project_root, service.port)
        self.root = tk.Tk()
        self.root.title("知境")
        self.root.resizable(False, False)
        assets = Path(__file__).with_name("assets")
        self.app_icon = tk.PhotoImage(master=self.root, file=str(assets / "liukanshan.png"))
        self.ball_icon = tk.PhotoImage(master=self.root, file=str(assets / "liukanshan-ball.png"))
        self.root.iconphoto(True, self.app_icon)
        self._closed = False
        self._ready = False
        self._starting = False
        self._pending_open = False
        self._events: queue.Queue = queue.Queue()
        self._drag: tuple[int, int, int, int] | None = None
        self._dragged = False
        self._build_ball()
        self.menu = tk.Menu(self.root, tearoff=False, font=("Microsoft YaHei UI", 10))
        self.menu.add_command(label="打开知境", command=self.show_chat)
        self.menu.add_command(label="收起", command=self.hide_chat)
        self.menu.add_separator()
        self._animate = tk.BooleanVar(master=self.root, value=True)
        self.menu.add_checkbutton(
            label="桌宠动画", variable=self._animate,
            command=lambda: self.animation.set_enabled(self._animate.get()),
        )
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.close)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self.root.after(100, self._drain_events)
        self._start_service()

    def _screen_bounds(self) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _build_ball(self) -> None:
        self.ball_size = 72
        transparent = "#FF00FF" if sys.platform == "win32" else "#F7F9FC"
        self.root.configure(bg=transparent)
        if sys.platform == "win32":
            self.root.overrideredirect(True)
            self.root.attributes("-transparentcolor", transparent)
        self.root.attributes("-topmost", True)
        self.ball = tk.Canvas(
            self.root,
            width=self.ball_size,
            height=self.ball_size,
            bg=transparent,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.ball.pack()
        self.animation = PetAnimation(self.ball, self.ball_icon)
        self.ball.bind("<Enter>", lambda _event: self.animation.hover(True))
        self.ball.bind("<Leave>", lambda _event: self.animation.hover(False))
        self.ball.bind("<ButtonPress-1>", self._on_ball_press)
        self.ball.bind("<B1-Motion>", self._on_ball_drag)
        self.ball.bind("<ButtonRelease-1>", self._on_ball_release)
        self.ball.bind("<Button-3>", self._show_menu)
        left, top, right, bottom = self._screen_bounds()
        self.root.geometry(
            f"{self.ball_size}x{self.ball_size}"
            f"{max(left, right - 92):+d}{max(top, bottom - 92):+d}"
        )

    def _show_menu(self, event) -> None:
        self.animation.hold()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self.animation.release()

    def _on_ball_press(self, event) -> None:
        self._drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._dragged = False
        self.animation.hold()

    def _on_ball_drag(self, event) -> None:
        if self._drag is None:
            return
        start_x, start_y, ball_x, ball_y = self._drag
        dx, dy = event.x_root - start_x, event.y_root - start_y
        if abs(dx) + abs(dy) >= 5:
            self._dragged = True
        if self._dragged:
            left, top, right, bottom = self._screen_bounds()
            x = min(max(ball_x + dx, left), right - self.ball_size)
            y = min(max(ball_y + dy, top), bottom - self.ball_size)
            self.root.geometry(f"{self.ball_size}x{self.ball_size}{x:+d}{y:+d}")

    def _on_ball_release(self, _event) -> None:
        clicked = self._drag is not None and not self._dragged
        self._drag = None
        self.animation.release(clicked=clicked)
        if clicked:
            self.toggle_chat()

    def _start_service(self) -> None:
        if self._starting or self._closed:
            return
        self._starting = True

        def start():
            try:
                self.service.ensure_running()
                with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
                    response = client.get(self.service.base_url + "/desktop")
                if (
                    response.status_code != 200
                    or 'data-desktop="true"' not in response.text
                    or 'data-surface="companion"' not in response.text
                ):
                    self._events.put(
                        (False, "当前运行的是旧版知境，请退出旧版后重新打开桌面助手。")
                    )
                    return
                self._events.put((True, ""))
            except DesktopServiceError as error:
                self._events.put((False, str(error)))
            except Exception:
                self._events.put((False, "暂时无法打开知境，请稍后点击刘看山重试。"))

        threading.Thread(target=start, name="zhijing-desktop-start", daemon=True).start()

    def show_chat(self) -> None:
        self._pending_open = True
        if self._ready:
            self._pending_open = False
            try:
                self.panel.show()
            except Exception:
                messagebox.showerror("知境", "随身助手打开失败，请重新打开知境。", parent=self.root)
        else:
            self._start_service()

    def hide_chat(self) -> None:
        self._pending_open = False
        self.panel.hide()

    def toggle_chat(self) -> None:
        if not self._ready:
            self._pending_open = not self._pending_open
            self._start_service()
        else:
            try:
                self.panel.toggle()
            except Exception:
                messagebox.showerror("知境", "随身助手打开失败，请重新打开知境。", parent=self.root)

    def _drain_events(self) -> None:
        if self._closed:
            return
        while not self._events.empty():
            ready, error = self._events.get_nowait()
            self._starting = False
            self._ready = ready
            if ready and self._pending_open:
                self.show_chat()
            elif error:
                self._pending_open = False
                messagebox.showerror("知境", error, parent=self.root)
        error = self.panel.poll_error()
        if error:
            messagebox.showerror("知境", error, parent=self.root)
        self.root.after(150, self._drain_events)

    def _on_destroy(self, event) -> None:
        if event.widget is self.root and not self._closed:
            self._closed = True
            self.animation.close()
            self.panel.shutdown()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.animation.close()
        self.panel.shutdown()
        self.root.destroy()


def run_desktop(service: Any) -> None:
    app = DesktopAssistant(service)
    try:
        app.root.mainloop()
    finally:
        app.panel.shutdown()
