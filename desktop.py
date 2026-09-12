"""Launch the desktop assistant independently of browser windows."""

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
PROJECT_ROOT = Path(sys.executable if FROZEN else __file__).resolve().parent
sys.dont_write_bytecode = True
if not FROZEN:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


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


def _write_check_report(report: dict, destination: Path | None) -> None:
    if destination is None and sys.stdout is None:
        from zhijing.desktop_paths import user_state_directory

        destination = user_state_directory() / "diagnostics" / "desktop-check.json"
    if destination is not None:
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        report["check_report"] = str(destination)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if sys.stdout is not None:
        try:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        except UnicodeEncodeError:
            print(json.dumps(report, ensure_ascii=True, indent=2))


def main() -> int:
    from zhijing.cli import valid_port
    from zhijing.desktop_paths import default_data_directory

    os.environ["ZHIJING_DATA_DIR"] = str(default_data_directory(PROJECT_ROOT))

    parser = argparse.ArgumentParser(description="知境随身工作台：点击刘看山开始阅读与整理")
    parser.add_argument("--port", type=valid_port, default=8000)
    parser.add_argument("--check", action="store_true", help="检查桌面依赖，不打开窗口")
    parser.add_argument("--check-report", type=Path, help="将 --check 结果写入 JSON 文件")
    parser.add_argument("--desktop-panel", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_report and not args.check:
        parser.error("--check-report 必须与 --check 一起使用")
    if args.desktop_panel:
        if not args.parent_pid or args.parent_pid < 1 or args.check:
            parser.error("工作台窗口必须由桌面助手启动")
        from zhijing.desktop_panel import run_panel

        try:
            return run_panel(PROJECT_ROOT, args.port, args.desktop_panel, args.parent_pid)
        except Exception:
            # The owning Tk process reports failures; do not create another GUI loop here.
            return 2
    if args.parent_pid:
        parser.error("--parent-pid 仅用于桌面工作台子进程")
    if args.check:
        from zhijing.startup import check_environment

        report = check_environment()
        report["frozen"] = FROZEN
        report["application_root"] = str(PROJECT_ROOT)
        try:
            import tkinter

            report["tk_version"] = tkinter.TkVersion
            report["tcl_version"] = tkinter.Tcl().eval("info patchlevel")
        except Exception:
            report["ready"] = False
            report["errors"].append(
                "桌面组件缺失，请重新解压完整软件包。"
                if FROZEN
                else "当前 Python 缺少可用 Tkinter/Tcl，请使用项目 Conda 环境。"
            )
        from zhijing.desktop_panel import check_webview

        report["desktop_panel"] = check_webview()
        if not report["desktop_panel"]["ready"]:
            report["ready"] = False
            report["errors"].extend(report["desktop_panel"]["errors"])
        _write_check_report(report, args.check_report)
        return 0 if report["ready"] else 2

    from tkinter import messagebox

    from zhijing.desktop_service import DesktopService
    from zhijing.desktop_ui import run_desktop

    with single_instance(args.port) as first:
        if not first:
            messagebox.showinfo("知境桌面助手", "悬浮助手已在运行，请点击桌面上的刘看山图标。")
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
