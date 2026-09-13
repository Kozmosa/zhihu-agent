"""Read rendered Zhihu answers in an isolated, user-operated WebView window."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from zhijing.features.zhihu.question_models import (
    normalize_question_url,
    question_id_from_url,
    raw_answer_to_draft,
)

MAX_RESULT_BYTES = 8 * 1024 * 1024
POLL_SECONDS = 1.8
STABLE_SECONDS = 15.0
TIMEOUT_SECONDS = 600.0
TERMINAL = {"ready", "failed", "cancelled"}
MESSAGES = {
    "running": "正在读取页面中已加载的回答；不会自动导入。",
    "needs_login": "请在知乎窗口内自行登录或完成验证，再回到问题继续读取。",
    "ready": "读取结束；仅收集页面中已加载、可读取的回答，请预览后选择导入。",
    "failed": "未能完成读取；可以重试，或复制正文后手动导入。",
    "cancelled": "读取已取消；已读取的内容仍可预览。",
}


def _encode(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _read_request(job_dir: Path) -> dict:
    path = job_dir / "request.json"
    if path.stat().st_size > 64 * 1024:
        raise ValueError("Invalid request")
    request = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Invalid request")
    request["url"] = normalize_question_url(request.get("url"))
    if type(request.get("count")) is not int or not 1 <= request["count"] <= 20:
        raise ValueError("Invalid count")
    if type(request.get("parent_pid")) is not int or not 0 < request["parent_pid"] < 2**32:
        raise ValueError("Invalid parent")
    profile = request.get("profile_dir")
    if not isinstance(profile, str) or not Path(profile).is_absolute():
        raise ValueError("Invalid browser profile")
    request["profile_dir"] = str(Path(profile).resolve())
    return request


class QuestionReadSession:
    """Bounded review-only results with serialized terminal-state transitions."""

    def __init__(self, job_dir: Path, request: dict):
        self.job_dir = job_dir
        self.request = request
        self.status = "running"
        self.items: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.last_progress: float | None = None
        self.fingerprint = None
        self.last_bytes = b""
        self._write()

    def _payload(self, status: str | None = None) -> dict:
        status = status or self.status
        return {"status": status, "message": MESSAGES[status], "items": list(self.items.values())}

    def _write(self, status: str | None = None) -> None:
        content = _encode(self._payload(status))
        if content == self.last_bytes:
            return
        temporary = self.job_dir / ("result-" + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_bytes(content)
            # Windows readers can briefly hold a destination without delete sharing.
            for attempt in range(6):
                try:
                    temporary.replace(self.job_dir / "result.json")
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.04)
        finally:
            temporary.unlink(missing_ok=True)
        self.last_bytes = content

    def finish(self, status: str) -> None:
        with self.lock:
            if self.status in TERMINAL:
                return
            # Commit the file first. A failed replacement must remain retryable.
            self._write(status)
            self.status = status

    def consume(self, snapshot, now: float) -> None:
        with self.lock:
            if self.status in TERMINAL or not isinstance(snapshot, dict):
                return
            state = snapshot.get("state")
            if state != "reading":
                self.status = "needs_login" if state in {"needs_login", "away"} else "running"
                self.last_progress = None
                self._write()
                return
            self.status = "running"
            candidates = snapshot.get("items")
            for raw in candidates[:20] if isinstance(candidates, list) else []:
                try:
                    draft = raw_answer_to_draft(raw, self.request["url"])
                except (ValueError, TypeError, UnicodeError):
                    continue
                answer_id = raw["answer_id"]
                previous = self.items.get(answer_id)
                if previous is not None and len(draft.text) <= len(previous["text"]):
                    continue
                item = {
                    "answer_id": answer_id,
                    "question_id": question_id_from_url(self.request["url"]),
                    "title": draft.title,
                    "author_name": draft.author_name,
                    "author_url": raw.get("author_url", ""),
                    "text": draft.text,
                    "url": str(draft.url),
                }
                # The public conversion accepts an absent/invalid author URL. Do not retain it.
                if not draft.provenance.external_author_id:
                    item["author_url"] = ""
                else:
                    kind, name = draft.provenance.external_author_id.split(":", 1)
                    item["author_url"] = f"https://www.zhihu.com/{kind}/{name}"
                self.items[answer_id] = item
                if len(_encode(self._payload("ready"))) > MAX_RESULT_BYTES:
                    if previous is None:
                        del self.items[answer_id]
                    else:
                        self.items[answer_id] = previous
                    self.finish("ready")
                    return
                if len(self.items) >= self.request["count"]:
                    self.finish("ready")
                    return
            fingerprint = (
                tuple((key, len(item["text"])) for key, item in self.items.items()),
                snapshot.get("scroll_y"),
                snapshot.get("height"),
            )
            if (
                fingerprint != self.fingerprint
                or snapshot.get("expanded")
                or self.last_progress is None
            ):
                self.fingerprint = fingerprint
                self.last_progress = now
            elif now - self.last_progress >= STABLE_SECONDS:
                self.finish("ready" if self.items else "failed")
                return
            self._write()


def _parent_handle(parent_pid: int):
    from zhijing.desktop_panel import _kernel

    kernel = _kernel()
    handle = kernel.OpenProcess(0x00100000, False, parent_pid)
    if not handle:
        raise OSError("Parent is unavailable")
    return kernel, handle


def run_question_browser(job_dir: Path) -> int:
    """Run one owned collection window; never expose a local application JS API."""
    job_dir = Path(job_dir).resolve()
    session = None
    kernel = handle = None
    window = None
    stopped = threading.Event()
    loaded = threading.Event()
    failed = threading.Event()
    threads: list[threading.Thread] = []
    try:
        request = _read_request(job_dir)
        session = QuestionReadSession(job_dir, request)
        kernel, handle = _parent_handle(request["parent_pid"])
        if kernel.WaitForSingleObject(handle, 0) != 258:
            session.finish("cancelled")
            return 0
        os.environ["PYTHONNET_RUNTIME"] = "netfx"
        import webview
        from webview.menu import Menu, MenuAction

        script = (Path(__file__).parent / "web" / "zhihu-question-reader.js").read_text(
            encoding="utf-8"
        )
        script = script.replace(
            "__ZHIHU_READER_REQUEST__",
            json.dumps(
                {"question_id": question_id_from_url(request["url"]), "count": request["count"]}
            ),
        )
        started = time.monotonic()

        def finish(status: str) -> None:
            try:
                session.finish(status)
            except Exception:
                failed.set()
            finally:
                stopped.set()
                if window is not None:
                    try:
                        window.destroy()
                    except Exception:
                        pass

        def navigate(target: str) -> None:
            if not stopped.is_set():
                loaded.clear()
                window.load_url(target)

        menu = [
            Menu(
                "读取",
                [
                    MenuAction("登录知乎", lambda: navigate("https://www.zhihu.com/signin")),
                    MenuAction("回到问题", lambda: navigate(request["url"])),
                    MenuAction("完成读取", lambda: finish("ready")),
                    MenuAction("取消", lambda: finish("cancelled")),
                ],
            )
        ]
        webview.settings["ALLOW_DOWNLOADS"] = False
        webview.settings["ALLOW_FILE_URLS"] = False
        window = webview.create_window(
            "知境 · 知乎问题读取",
            request["url"],
            js_api=None,
            width=1050,
            height=760,
            min_size=(600, 420),
            on_top=False,
            text_select=True,
            menu=menu,
        )

        def closed() -> None:
            try:
                session.finish("cancelled")
            except Exception:
                failed.set()
            finally:
                stopped.set()

        window.events.loaded += loaded.set
        window.events.closed += closed

        def watch() -> None:
            while not stopped.wait(0.15):
                if (job_dir / "cancel.flag").exists() or kernel.WaitForSingleObject(
                    handle, 0
                ) != 258:
                    finish("cancelled")
                    return
                if time.monotonic() - started >= TIMEOUT_SECONDS:
                    finish("ready" if session.items else "failed")
                    return

        def poll() -> None:
            while not stopped.is_set():
                if loaded.is_set():
                    try:
                        snapshot = window.evaluate_js(script)
                    except Exception:
                        # Navigation and incomplete DOM can interrupt evaluation. Never log the page.
                        snapshot = None
                    try:
                        session.consume(snapshot, time.monotonic())
                    except Exception:
                        # Processing or persistent file errors must not leave an invisible stuck job.
                        failed.set()
                        finish("failed")
                        return
                    if session.status in TERMINAL:
                        finish(session.status)
                        return
                stopped.wait(POLL_SECONDS)

        def start_threads() -> None:
            for action in (watch, poll):
                thread = threading.Thread(target=action, daemon=True)
                threads.append(thread)
                thread.start()

        Path(request["profile_dir"]).mkdir(parents=True, exist_ok=True)
        webview.start(
            start_threads,
            gui="edgechromium",
            private_mode=False,
            storage_path=request["profile_dir"],
            debug=False,
        )
        session.finish("cancelled")
        return 1 if failed.is_set() or session.status == "failed" else 0
    except Exception:
        try:
            if session is None:
                # A malformed request must still produce a safe, inspectable result when possible.
                session = QuestionReadSession(job_dir, {})
            session.finish("failed")
        except Exception:
            pass
        return 1
    finally:
        stopped.set()
        for thread in threads:
            thread.join(timeout=2)
        if kernel is not None and handle:
            kernel.CloseHandle(handle)
