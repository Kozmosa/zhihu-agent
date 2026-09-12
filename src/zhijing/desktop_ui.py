"""Native desktop assistant. Network work stays off Tk's event thread."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import Any
from urllib.parse import urlsplit

BLUE = "#2563EB"
INK = "#14213D"
MUTED = "#687893"
LINE = "#E1E7F0"
PAPER = "#F7F9FC"
MODES = {"extractive": "离线摘录", "ollama": "Ollama 模型", "openai": "API 模型"}


class DesktopAssistant:
    """A draggable desktop ball and a separate, reusable native chat window."""

    def __init__(self, service: Any):
        self.service = service
        self.root = tk.Tk()
        self.root.title("知境桌面助手")
        self.root.resizable(False, False)
        assets = Path(__file__).with_name("assets")
        self.app_icon = tk.PhotoImage(master=self.root, file=str(assets / "liukanshan.png"))
        self.ball_icon = tk.PhotoImage(master=self.root, file=str(assets / "liukanshan-ball.png"))
        self.header_icon = tk.PhotoImage(
            master=self.root, file=str(assets / "liukanshan-header.png")
        )
        self.root.iconphoto(True, self.app_icon)
        self._closed = False
        self._events: queue.Queue = queue.Queue()
        self._initializing = False
        self._loading_sources = False
        self._health_revision = 0
        self._link_tags: list[str] = []
        self._drag: tuple[int, int, int, int] | None = None
        self._dragged = False
        self.ready = False
        self.busy = False
        self.sources: list[dict] = []
        self.selected_source: dict | None = None
        self.source_revision = 0
        self.page = 0
        self.has_more = False
        self._choices: list[dict | None] = []
        self.font = "Microsoft YaHei UI" if sys.platform == "win32" else "TkDefaultFont"
        self._build_ball()
        self._build_chat()
        self._build_menu()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self._update_controls()
        self.root.after(50, self._drain_events)
        self._start_service()

    def _screen_bounds(self) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _build_ball(self) -> None:
        self.ball_size = 64
        transparent = "#FF00FF"
        if sys.platform == "win32":
            self.root.overrideredirect(True)
            self.root.configure(bg=transparent)
            self.root.attributes("-transparentcolor", transparent)
        else:
            transparent = PAPER
            self.root.configure(bg=PAPER)
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
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
        self.ball.create_image(32, 32, image=self.ball_icon)
        self.ball.bind("<ButtonPress-1>", self._on_ball_press)
        self.ball.bind("<B1-Motion>", self._on_ball_drag)
        self.ball.bind("<ButtonRelease-1>", self._on_ball_release)
        self.ball.bind("<Button-3>", self._show_menu)
        left, top, right, bottom = self._screen_bounds()
        x, y = max(left, right - 92), max(top, bottom - 92)
        self.root.geometry(f"64x64{x:+d}{y:+d}")

    def _build_chat(self) -> None:
        self.chat_window = tk.Toplevel(self.root)
        self.chat_window.withdraw()
        self.chat_window.title("知境 · 桌面问答")
        self.chat_window.iconphoto(False, self.app_icon)
        self.chat_window.configure(bg="white")
        self.chat_window.geometry("440x680")
        self.chat_window.minsize(360, 460)
        try:
            self.chat_window.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.chat_window.protocol("WM_DELETE_WINDOW", self.hide_chat)
        self.chat_window.bind("<Escape>", lambda _event: self.hide_chat())
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Zhijing.TButton",
            font=(self.font, 9),
            padding=(10, 6),
            background="white",
            foreground=INK,
            bordercolor=LINE,
            lightcolor="white",
            darkcolor=LINE,
            relief="flat",
        )
        style.map(
            "Zhijing.TButton",
            background=[("active", "#EDF4FF"), ("disabled", PAPER)],
            foreground=[("disabled", "#9AA7BD")],
        )
        style.configure(
            "Zhijing.TCombobox",
            font=(self.font, 10),
            padding=5,
            foreground=INK,
            fieldbackground="white",
            bordercolor=LINE,
        )
        style.map("Zhijing.TCombobox", fieldbackground=[("readonly", "white")])

        header = tk.Frame(self.chat_window, bg="white", padx=20, pady=14)
        header.pack(fill="x")
        tk.Label(header, image=self.header_icon, bg="white").pack(side="left", padx=(0, 12))
        titles = tk.Frame(header, bg="white")
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text="知境问答", bg="white", fg=INK, font=(self.font, 13, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            titles, text="桌面常驻，随时阅读与思考", bg="white", fg=MUTED, font=(self.font, 9)
        ).pack(anchor="w")
        ttk.Button(header, text="收起", command=self.hide_chat, style="Zhijing.TButton").pack(
            side="right"
        )
        tk.Frame(self.chat_window, bg=LINE, height=1).pack(fill="x")

        picker = tk.Frame(self.chat_window, bg=PAPER, padx=16, pady=10)
        picker.pack(fill="x")
        self.scope_var = tk.StringVar(value="先选择一份资料，再开始问答")
        self.scope_label = tk.Label(
            picker,
            textvariable=self.scope_var,
            bg=PAPER,
            fg=INK,
            anchor="w",
            justify="left",
            wraplength=394,
            font=(self.font, 9, "bold"),
        )
        self.scope_label.pack(fill="x", pady=(0, 7))
        row = tk.Frame(picker, bg=PAPER)
        row.pack(fill="x")
        self.source_combo = ttk.Combobox(row, state="readonly", style="Zhijing.TCombobox")
        self.source_combo.pack(side="left", fill="x", expand=True)
        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_selected)
        self.refresh_button = ttk.Button(
            row,
            text="刷新",
            command=self.refresh_sources,
            style="Zhijing.TButton",
        )
        self.refresh_button.pack(side="left", padx=(7, 0))
        pages = tk.Frame(picker, bg=PAPER)
        pages.pack(fill="x", pady=(7, 0))
        self.previous_button = ttk.Button(
            pages,
            text="上一页",
            command=lambda: self.refresh_sources(self.page - 1),
            style="Zhijing.TButton",
        )
        self.previous_button.pack(side="left")
        self.page_var = tk.StringVar(value="第 1 页")
        tk.Label(pages, textvariable=self.page_var, bg=PAPER, fg=MUTED, font=(self.font, 9)).pack(
            side="left", padx=12
        )
        self.next_button = ttk.Button(
            pages,
            text="下一页",
            command=lambda: self.refresh_sources(self.page + 1),
            style="Zhijing.TButton",
        )
        self.next_button.pack(side="left")
        self.mode_var = tk.StringVar(value="正在连接本地服务…")
        tk.Label(
            self.chat_window,
            textvariable=self.mode_var,
            bg="white",
            fg=MUTED,
            wraplength=398,
            anchor="w",
            justify="left",
            font=(self.font, 9),
            padx=16,
        ).pack(fill="x", pady=(9, 3))

        composer = tk.Frame(self.chat_window, bg="white", padx=16, pady=12)
        composer.pack(side="bottom", fill="x")
        tk.Label(
            composer,
            text="每个问题独立依据当前资料回答 · 重要结论请核对来源",
            bg="white",
            fg=MUTED,
            font=(self.font, 8),
            wraplength=395,
            justify="left",
        ).pack(side="bottom", anchor="w", pady=(7, 0))
        bottom = tk.Frame(composer, bg="white")
        bottom.pack(side="bottom", fill="x", pady=(6, 0))
        tk.Label(
            bottom, text="Enter 发送 · Shift+Enter 换行", bg="white", fg=MUTED, font=(self.font, 8)
        ).pack(side="left")
        self.send_button = tk.Button(
            bottom,
            text="发送 ↑",
            command=self.send_question,
            bg=BLUE,
            fg="white",
            activebackground="#1D4ED8",
            activeforeground="white",
            disabledforeground="#CAD7F4",
            bd=0,
            relief="flat",
            padx=17,
            pady=6,
            cursor="hand2",
            font=(self.font, 10, "bold"),
        )
        self.send_button.pack(side="right")
        self.question = tk.Text(
            composer,
            height=3,
            wrap="word",
            font=(self.font, 10),
            bg="#FBFCFF",
            fg=INK,
            relief="flat",
            highlightthickness=1,
            highlightbackground=LINE,
            highlightcolor=BLUE,
            padx=10,
            pady=8,
            undo=True,
        )
        self.question.pack(fill="x")
        self.question.bind("<Return>", self._on_return)
        self.question.bind("<KP_Enter>", self._on_return)
        self.status_var = tk.StringVar(value="正在准备服务，可以先收起窗口。")
        self.status_label = tk.Label(
            self.chat_window,
            textvariable=self.status_var,
            bg="white",
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=396,
            font=(self.font, 9),
            padx=16,
        )
        self.status_label.pack(side="bottom", fill="x", pady=(3, 0))
        self.transcript = scrolledtext.ScrolledText(
            self.chat_window,
            wrap="word",
            bg="white",
            fg=INK,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(self.font, 10),
            padx=16,
            pady=10,
            state="disabled",
            height=8,
        )
        self.transcript.pack(fill="both", expand=True)
        self.transcript.tag_configure("user_label", foreground=BLUE, font=(self.font, 10, "bold"))
        self.transcript.tag_configure(
            "assistant_label", foreground=INK, font=(self.font, 10, "bold")
        )
        self.transcript.tag_configure("meta", foreground=MUTED, font=(self.font, 9))
        self.transcript.tag_configure("quote", foreground=MUTED, lmargin1=10, lmargin2=10)
        self.transcript.bind("<Control-a>", self._select_transcript)
        self.chat_window.bind("<Configure>", self._resize_labels, add="+")

    def _resize_labels(self, event) -> None:
        if event.widget is self.chat_window:
            width = max(250, event.width - 36)
            self.scope_label.configure(wraplength=width)
            self.status_label.configure(wraplength=width)

    def _build_menu(self) -> None:
        self.menu = tk.Menu(self.root, tearoff=False, font=(self.font, 10))
        self.menu.add_command(label="打开问答", command=self.show_chat)
        self.menu.add_separator()
        self.menu.add_command(
            label="打开工作台", command=lambda: self._open_service_page("/workspace")
        )
        self.menu.add_command(
            label="采集知乎资料", command=lambda: self._open_service_page("/workspace#companion")
        )
        self.menu.add_command(label="模型设置", command=lambda: self._open_service_page("/"))
        self.menu.add_separator()
        self.menu.add_command(label="退出桌面助手", command=self.close)

    def _show_menu(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _on_ball_press(self, event) -> None:
        self._drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self._dragged = False

    def _on_ball_drag(self, event) -> None:
        if self._drag is None:
            return
        start_x, start_y, ball_x, ball_y = self._drag
        dx, dy = event.x_root - start_x, event.y_root - start_y
        if abs(dx) + abs(dy) >= 5:
            self._dragged = True
        if not self._dragged:
            return
        left, top, right, bottom = self._screen_bounds()
        x = min(max(ball_x + dx, left), right - self.ball_size)
        y = min(max(ball_y + dy, top), bottom - self.ball_size)
        self.root.geometry(f"64x64{x:+d}{y:+d}")

    def _on_ball_release(self, _event) -> None:
        if self._drag is not None and not self._dragged:
            self.toggle_chat()
        self._drag = None

    def toggle_chat(self) -> None:
        if self.chat_window.state() == "normal":
            self.hide_chat()
        else:
            self.show_chat()

    def show_chat(self) -> None:
        left, top, right, bottom = self._screen_bounds()
        width = min(440, right - left - 20)
        height = min(680, bottom - top - 20)
        x = min(max(self.root.winfo_x() - width - 12, left + 8), right - width - 8)
        y = min(max(self.root.winfo_y() + self.ball_size - height, top + 8), bottom - height - 8)
        self.chat_window.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self.chat_window.deiconify()
        self.chat_window.lift()
        self.question.focus_set()
        if self.ready:
            self._health_revision += 1
            self._work("health", self.service.get_health, revision=self._health_revision)

    def hide_chat(self) -> None:
        self.chat_window.withdraw()
        self.ball.focus_set()

    def _open_service_page(self, path: str) -> None:
        if not self.ready:
            self.show_chat()
            self._set_status("本地服务尚未就绪；请稍候，或点击刷新重试。")
            return
        self._open_url(self.service.base_url.rstrip("/") + path)

    @staticmethod
    def _open_url(url: str) -> None:
        try:
            parsed = urlsplit(url)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                webbrowser.open(url, new=2)
        except (ValueError, webbrowser.Error):
            pass

    def _work(self, kind: str, function: Callable, **context) -> None:
        def run():
            try:
                self._events.put((kind, function(), None, context))
            except Exception as error:
                self._events.put((kind, None, str(error), context))

        threading.Thread(target=run, daemon=True, name="zhijing-desktop-" + kind).start()

    def _start_service(self) -> None:
        if self._initializing:
            return
        self._initializing = True
        self._update_controls()

        def start():
            self.service.ensure_running()
            return self.service.get_health()

        self._work("startup", start)

    def _drain_events(self) -> None:
        if self._closed:
            return
        for _ in range(30):
            try:
                kind, result, error, context = self._events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(kind, result, error, context)
        if not self._closed:
            self.root.after(50, self._drain_events)

    def _handle_event(self, kind: str, result: Any, error: str | None, context: dict) -> None:
        if kind == "startup":
            self._initializing = False
            if error:
                self._set_status("服务启动未完成：" + error + "；可点击刷新重试。", error=True)
            else:
                self.ready = True
                self._set_mode(result)
                self._set_status("服务已就绪，选择一份资料开始问答。")
                self.refresh_sources()
        elif kind == "health":
            if context["revision"] == self._health_revision:
                if error:
                    self.mode_var.set("暂时无法读取模式，请检查本地服务。")
                else:
                    self._set_mode(result)
        elif kind == "sources":
            self._loading_sources = False
            if error or not isinstance(result, list):
                self._set_status("读取资料失败：" + (error or "服务返回了无效列表。"), error=True)
            else:
                self.page = context["page"]
                self.has_more = len(result) > 20
                self.sources = result[:20]
                self._render_sources()
                if not self.sources:
                    self._set_status("本页没有资料。可右键悬浮球打开工作台，导入后刷新。")
                elif not self.selected_source:
                    self._set_status("请选择一份资料，然后输入问题。")
        elif kind == "answer":
            self.busy = False
            if context["revision"] != self.source_revision:
                self._update_controls()
                return
            if error:
                if not self.question.get("1.0", "end-1c").strip():
                    self.question.insert("1.0", context["question"])
                self._set_status(error, error=True)
            elif (
                not isinstance(result, dict)
                or not isinstance(result.get("answer"), dict)
                or not isinstance(result["answer"].get("answer"), str)
            ):
                if not self.question.get("1.0", "end-1c").strip():
                    self.question.insert("1.0", context["question"])
                self._set_status("问答响应格式无效，请重试。", error=True)
            else:
                self._set_mode(result["health"])
                self._append_answer(result["answer"])
                self._set_status("回答完成。引用可点击核对，文字可选择复制。")
        self._update_controls()

    def _set_mode(self, health: dict) -> None:
        provider = health.get("model_provider") if isinstance(health, dict) else None
        if provider == "extractive":
            self.mode_var.set("离线摘录 · 使用已导入内容，无模型请求")
        elif provider in MODES:
            self.mode_var.set(MODES[provider] + " · 问题和相关资料会发送到已配置模型服务")
        else:
            self.mode_var.set("模式未知，请到模型设置确认。")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg="#B13A36" if error else MUTED)

    def _update_controls(self) -> None:
        waiting = self._initializing or self._loading_sources
        self.refresh_button.configure(state="disabled" if waiting else "normal")
        self.source_combo.configure(state="disabled" if waiting or not self.ready else "readonly")
        self.previous_button.configure(state="disabled" if waiting or self.page == 0 else "normal")
        self.next_button.configure(state="disabled" if waiting or not self.has_more else "normal")
        self.send_button.configure(
            state="normal" if self.ready and self.selected_source and not self.busy else "disabled"
        )

    def refresh_sources(self, page: int = 0) -> None:
        if not self.ready:
            self._start_service()
            return
        if self._loading_sources:
            return
        self._loading_sources = True
        page = max(0, page)
        self._set_status("正在读取本地资料…")
        self._update_controls()
        self._work(
            "sources", lambda: self.service.list_sources(offset=page * 20, limit=21), page=page
        )

    def _render_sources(self) -> None:
        rows = list(self.sources)
        if self.selected_source and not any(
            row["id"] == self.selected_source["id"] for row in rows
        ):
            rows.insert(0, self.selected_source)
        self._choices = [None, *rows]
        labels = ["请选择问答资料…" if rows else "暂无资料，请先到工作台导入"]
        for source in rows:
            prefix = "[摘要] " if source.get("content_extent") == "excerpt" else ""
            labels.append(prefix + source["title"][:90] + " · " + source["author_name"][:24])
        self.source_combo.configure(values=labels)
        index = next(
            (
                i
                for i, source in enumerate(self._choices)
                if source and self.selected_source and source["id"] == self.selected_source["id"]
            ),
            0,
        )
        self.source_combo.current(index)
        self.page_var.set(f"第 {self.page + 1} 页")

    def _on_source_selected(self, _event) -> None:
        index = self.source_combo.current()
        if 0 <= index < len(self._choices):
            self.select_source(self._choices[index])

    def select_source(self, source: dict | None) -> None:
        old_id = self.selected_source.get("id") if self.selected_source else None
        new_id = source.get("id") if source else None
        self.selected_source = source
        if old_id != new_id:
            self.source_revision += 1
            self.transcript.configure(state="normal")
            self.transcript.delete("1.0", "end")
            for tag in self._link_tags:
                self.transcript.tag_delete(tag)
            self._link_tags.clear()
            self.transcript.configure(state="disabled")
            self.question.delete("1.0", "end")
        if source:
            prefix = "仅依据摘要 · " if source.get("content_extent") == "excerpt" else "当前资料 · "
            self.scope_var.set(prefix + source["title"])
            self._set_status("已选择资料。每个问题独立作答，切换资料会清空对话显示。")
        else:
            self.scope_var.set("先选择一份资料，再开始问答")
            self._set_status("请选择资料；还没有资料时，可右键打开工作台导入。")
        self._render_sources()
        self._update_controls()

    def _on_return(self, event):
        if event.state & 0x0001 or getattr(event, "keycode", None) == 229 or self._ime_composing():
            return None
        self.send_question()
        return "break"

    def _ime_composing(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            from ctypes import wintypes

            imm = ctypes.windll.imm32
            imm.ImmGetContext.argtypes = [wintypes.HWND]
            imm.ImmGetContext.restype = wintypes.HANDLE
            imm.ImmGetCompositionStringW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            imm.ImmGetCompositionStringW.restype = wintypes.LONG
            imm.ImmReleaseContext.argtypes = [wintypes.HWND, wintypes.HANDLE]
            imm.ImmReleaseContext.restype = wintypes.BOOL
            user32 = ctypes.windll.user32
            user32.GetFocus.restype = wintypes.HWND
            hwnd = user32.GetFocus() or self.question.winfo_id()
            context = imm.ImmGetContext(hwnd)
            if not context:
                return False
            try:
                return imm.ImmGetCompositionStringW(context, 0x0008, None, 0) > 0
            finally:
                imm.ImmReleaseContext(hwnd, context)
        except (AttributeError, OSError, tk.TclError):
            return False

    def send_question(self) -> None:
        if self.busy:
            return
        if not self.ready or not self.selected_source:
            self._set_status("请等待服务就绪，并先选择一份资料。", error=True)
            return
        question = self.question.get("1.0", "end-1c").strip()
        if not question or len(question) > 2000:
            self._set_status("请填写 1 至 2,000 字符的问题。", error=True)
            return
        source = dict(self.selected_source)
        revision = self.source_revision
        self.busy = True
        self.question.delete("1.0", "end")
        self._insert("你\n", "user_label")
        self._insert(question + "\n\n")
        self._set_status("正在根据已导入资料回答…")
        self._update_controls()

        def ask():
            health = self.service.get_health()
            return {"health": health, "answer": self.service.ask(source, question)}

        self._work("answer", ask, revision=revision, question=question)

    def _insert(self, text: str, tag: str | None = None) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text, () if tag is None else (tag,))
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _append_answer(self, result: dict) -> None:
        mode = MODES.get(result.get("mode"), "资料问答")
        self._insert("知境 · " + mode + "\n", "assistant_label")
        self._insert(str(result.get("answer", "服务未返回回答内容。")) + "\n\n")
        notice = result.get("identity_notice", "助手根据已导入资料回答，不代表作者本人。")
        self._insert(str(notice) + "\n\n", "meta")
        for index, citation in enumerate(result.get("citations", []), 1):
            self._insert(f"[{index}] {citation.get('title', '参考资料')}\n", "assistant_label")
            self._insert(str(citation.get("excerpt", "")) + "\n", "quote")
            url = citation.get("url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                safe = parsed and parsed.scheme in {"http", "https"} and parsed.netloc
            except ValueError:
                safe = False
            if safe:
                tag = "source_link_" + str(len(self._link_tags))
                self._link_tags.append(tag)
                self.transcript.tag_configure(tag, foreground=BLUE, underline=True)
                self.transcript.tag_bind(
                    tag, "<Button-1>", lambda _event, value=url: self._open_url(value)
                )
                self.transcript.tag_bind(
                    tag, "<Enter>", lambda _event: self.transcript.configure(cursor="hand2")
                )
                self.transcript.tag_bind(
                    tag, "<Leave>", lambda _event: self.transcript.configure(cursor="xterm")
                )
                self._insert("打开来源网页 ↗\n", tag)
            self._insert("\n")
        if result.get("citation_notice"):
            self._insert(str(result["citation_notice"]) + "\n\n", "meta")

    def _select_transcript(self, _event):
        self.transcript.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _on_destroy(self, event) -> None:
        if event.widget is self.root:
            self._closed = True

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.root.destroy()


def run_desktop(service: Any) -> None:
    """Block in Tk until the user exits; the entry point owns service shutdown."""
    assistant = DesktopAssistant(service)
    assistant.root.mainloop()
