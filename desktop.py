"""Launch the desktop assistant independently of browser windows."""

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ZHIJING_DATA_DIR", str(PROJECT_ROOT / "data"))


@contextmanager
def single_instance(port: int):
    """Keep one desktop assistant per project and port in the Windows session."""
    if os.name != "nt":
        yield True
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    identity = hashlib.sha256(f"{str(PROJECT_ROOT).lower()}:{port}".encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, False, "Local\\ZhijingDesktop-" + identity)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    already_running = ctypes.get_last_error() == 183
    try:
        yield not already_running
    finally:
        kernel.CloseHandle(handle)


def main() -> int:
    from zhijing.cli import valid_port

    parser = argparse.ArgumentParser(description="知境桌面悬浮助手：关闭网页后仍可问答")
    parser.add_argument("--port", type=valid_port, default=8000)
    parser.add_argument("--check", action="store_true", help="检查桌面依赖，不打开窗口")
    args = parser.parse_args()
    if args.check:
        from zhijing.startup import check_environment

        report = check_environment()
        try:
            import tkinter

            report["tk_version"] = tkinter.TkVersion
        except ImportError:
            report["ready"] = False
            report["errors"].append("当前 Python 缺少 Tkinter，请使用项目 Conda 环境。")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 2

    from tkinter import messagebox

    from zhijing.desktop_service import DesktopService
    from zhijing.desktop_ui import run_desktop

    with single_instance(args.port) as first:
        if not first:
            messagebox.showinfo("知境桌面助手", "悬浮助手已在运行，请点击桌面右下角的蓝色悬浮球。")
            return 0
        service = DesktopService(PROJECT_ROOT, port=args.port)
        try:
            run_desktop(service)
        finally:
            service.shutdown()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # pythonw has no console; give startup failures a visible, actionable message.
        from tkinter import messagebox

        messagebox.showerror("知境桌面助手启动失败", str(error))
        raise SystemExit(1) from error
