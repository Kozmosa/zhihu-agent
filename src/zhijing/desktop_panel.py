"""Windows WebView workbench with a private, owned parent/child lifecycle."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from importlib.metadata import version
from pathlib import Path

EVENT_NAMES = ("show", "hide", "toggle", "quit", "ready", "visible")


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    for name in ("SetEvent", "ResetEvent", "CloseHandle"):
        getattr(kernel, name).argtypes = [wintypes.HANDLE]
        getattr(kernel, name).restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    return kernel


class PanelEvents:
    """Session-local named events work without stdout or extra TCP listeners."""

    def __init__(self, session: str, *, create: bool):
        if not re.fullmatch(r"[0-9a-f]{32}", session):
            raise ValueError("Invalid desktop panel session.")
        self.kernel = _kernel()
        self.handles = {}
        try:
            for name in EVENT_NAMES:
                identity = f"Local\\ZhijingPanel-{session}-{name}"
                handle = (
                    self.kernel.CreateEventW(None, name in {"ready", "visible"}, False, identity)
                    if create
                    else self.kernel.OpenEventW(0x00100002, False, identity)
                )
                if not handle:
                    raise OSError("Cannot connect to desktop window controls.")
                self.handles[name] = handle
        except Exception:
            self.close()
            raise

    def set(self, name: str) -> None:
        self.kernel.SetEvent(self.handles[name])

    def reset(self, name: str) -> None:
        self.kernel.ResetEvent(self.handles[name])

    def is_set(self, name: str) -> bool:
        return self.kernel.WaitForSingleObject(self.handles[name], 0) == 0

    def close(self) -> None:
        for handle in self.handles.values():
            self.kernel.CloseHandle(handle)
        self.handles.clear()


class PanelController:
    """Own exactly one child process; no global PID or process-name termination."""

    def __init__(self, project_root: Path, port: int):
        self.project_root = Path(project_root).resolve()
        self.port = port
        self.process: subprocess.Popen | None = None
        self.events: PanelEvents | None = None
        self.started_at = 0.0

    def _alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _launch(self) -> None:
        self.shutdown()
        session = uuid.uuid4().hex
        self.events = PanelEvents(session, create=True)
        arguments = [
            "--port",
            str(self.port),
            "--desktop-panel",
            session,
            "--parent-pid",
            str(os.getpid()),
        ]
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command += ["-s", "-B", str(self.project_root / "desktop.py")]
        environment = os.environ.copy()
        for name in ("ZHIHU_ACCESS_SECRET", "ZHIJING_OPENAI_API_KEY", "ZHIJING_OLLAMA_API_KEY"):
            environment.pop(name, None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            self.process = subprocess.Popen(
                command + arguments,
                cwd=self.project_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.started_at = time.monotonic()
        except Exception:
            self.events.close()
            self.events = None
            raise

    def show(self) -> None:
        if not self._alive():
            self._launch()
        else:
            self.events.set("show")

    def hide(self) -> None:
        if self._alive():
            self.events.set("hide")

    def toggle(self) -> None:
        if not self._alive():
            self._launch()
        else:
            self.events.set("toggle")

    def poll_error(self) -> str | None:
        if self.process is None:
            return None
        exited = self.process.poll() is not None
        timeout = not self.events.is_set("ready") and time.monotonic() - self.started_at > 45
        if exited or timeout:
            self.shutdown()
            return (
                "工作台未能启动。请确认 Microsoft Edge WebView2 Runtime 已安装，再点击刘看山重试。"
            )
        return None

    def shutdown(self) -> None:
        if self._alive():
            self.events.set("quit")
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self.process = None
        if self.events is not None:
            self.events.close()
            self.events = None


def check_webview() -> dict:
    """Inspect dependencies and installed runtime without opening windows."""
    report = {"ready": True, "renderer": "edgechromium", "errors": []}
    try:
        report["pywebview"] = version("pywebview")
        report["pythonnet"] = version("pythonnet")
        os.environ["PYTHONNET_RUNTIME"] = "netfx"
        import clr  # noqa: F401
        import webview  # noqa: F401
        from webview.platforms import edgechromium

        report["renderer"] = edgechromium.renderer
    except Exception:
        report["ready"] = False
        report["errors"].append("桌面工作台组件不可用，请重新解压完整软件包或安装 desktop 依赖。")
        return report
    import winreg

    versions = []
    runtime_id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(
                    hive,
                    "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + runtime_id,
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    runtime_version = winreg.QueryValueEx(key, "pv")[0]
                    if runtime_version and runtime_version != "0.0.0.0":
                        versions.append(runtime_version)
            except OSError:
                pass
    report["webview2_runtime"] = sorted(set(versions))
    if not versions:
        report["ready"] = False
        report["errors"].append("请安装 Microsoft Edge WebView2 Runtime 后重新打开知境。")
    return report


def panel_geometry() -> dict:
    rect = wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        width = max(320, min(1060, rect.right - rect.left - 32))
        height = max(240, min(780, rect.bottom - rect.top - 32))
        return {
            "width": width,
            "height": height,
            "min_size": (min(760, width), min(600, height)),
            "x": rect.left + (rect.right - rect.left - width) // 2,
            "y": rect.top + (rect.bottom - rect.top - height) // 2,
        }
    return {"width": 1060, "height": 780, "min_size": (760, 600)}


def run_panel(project_root: Path, port: int, session: str, parent_pid: int) -> int:
    """Child entry runs before any Tk or service construction."""
    os.environ["PYTHONNET_RUNTIME"] = "netfx"
    import webview

    from zhijing.desktop_paths import default_data_directory

    events = PanelEvents(session, create=False)
    kernel = events.kernel
    parent = kernel.OpenProcess(0x00100000, False, parent_pid)
    if not parent:
        events.close()
        return 2
    stopping, shown, pending_hide = threading.Event(), threading.Event(), threading.Event()
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(
        "知境 · 随身工作台",
        f"http://127.0.0.1:{port}/desktop",
        resizable=True,
        on_top=True,
        background_color="#F7F9FC",
        text_select=True,
        **panel_geometry(),
    )

    def on_shown():
        shown.set()
        events.set("visible")

    def hide():
        window.hide()
        events.reset("visible")

    def closing():
        if stopping.is_set():
            return True
        # Defer GUI changes until WinForms has finished deciding whether to close.
        pending_hide.set()
        return False

    def controls():
        while not stopping.is_set():
            if events.is_set("quit") or kernel.WaitForSingleObject(parent, 0) == 0:
                stopping.set()
                if shown.wait(10):
                    window.destroy()
                return
            if shown.is_set():
                if pending_hide.is_set() or events.is_set("hide"):
                    pending_hide.clear()
                    hide()
                if events.is_set("show"):
                    window.show()
                    window.restore()
                    events.set("visible")
                if events.is_set("toggle"):
                    if events.is_set("visible"):
                        hide()
                    else:
                        window.show()
                        window.restore()
                        events.set("visible")
            stopping.wait(0.08)

    window.events.shown += on_shown
    window.events.loaded += lambda: events.set("ready")
    window.events.minimized += lambda: events.reset("visible")
    window.events.closing += closing
    window.events.closed += stopping.set
    worker = threading.Thread(target=controls, name="zhijing-panel-controls", daemon=True)
    try:
        storage = default_data_directory(project_root) / "desktop-webview"
        storage.mkdir(parents=True, exist_ok=True)
        webview.start(
            worker.start,
            gui="edgechromium",
            debug=False,
            private_mode=False,
            storage_path=str(storage),
            icon=str(Path(__file__).with_name("assets") / "liukanshan.ico"),
        )
        return 0
    finally:
        stopping.set()
        if worker.ident is not None:
            worker.join(timeout=2)
        kernel.CloseHandle(parent)
        events.close()
