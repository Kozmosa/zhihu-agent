import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from zhijing import zhihu_browser as browser


def answer(identifier="1", **changes):
    value = {
        "answer_id": identifier,
        "question_id": "123",
        "title": "合成问题",
        "author_name": "合成作者",
        "author_url": "https://www.zhihu.com/people/fixture",
        "text": "第一段正文。\n\n第二段正文。",
        "url": f"https://www.zhihu.com/question/123/answer/{identifier}",
    }
    return value | changes


@pytest.fixture
def request_file(tmp_path):
    request = {
        "url": "https://www.zhihu.com/question/123",
        "count": 2,
        "parent_pid": 1234,
        "profile_dir": str(tmp_path / "zhihu-browser"),
    }
    (tmp_path / "request.json").write_text(json.dumps(request), encoding="utf-8")
    return tmp_path, request


def read_result(path):
    return json.loads((path / "result.json").read_text(encoding="utf-8"))


def test_author_session_retains_each_question_and_excludes_other_authors(request_file):
    path, request = request_file
    request["url"] = "https://www.zhihu.com/people/fixture/answers"
    session = browser.QuestionReadSession(path, request)
    session.consume(
        {
            "state": "reading",
            "items": [
                answer(),
                answer(
                    "2",
                    question_id="456",
                    url="https://www.zhihu.com/question/456/answer/2",
                    title="另一个问题",
                ),
                answer("3", author_url="https://www.zhihu.com/people/other"),
            ],
        },
        0,
    )
    result = read_result(path)
    assert {item["question_id"] for item in result["items"]} == {"123", "456"}
    assert len(result["items"]) == 2


def test_only_valid_unique_same_question_bodies_are_preserved(request_file):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    session.consume(
        {
            "state": "reading",
            "items": [
                answer(),
                answer(),
                answer("2", question_id="456"),
                answer("3", text="x" * 100001),
                answer("4", author_url="https://example.test/private?secret=synthetic"),
            ],
        },
        0,
    )
    result = read_result(path)
    assert result["status"] == "ready"
    assert [item["answer_id"] for item in result["items"]] == ["1", "4"]
    assert result["items"][0]["text"] == "第一段正文。\n\n第二段正文。"
    assert result["items"][1]["author_url"] == ""
    assert not list(path.glob("*.tmp"))


def test_login_pauses_stability_and_terminal_cancel_keeps_preview(request_file):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    snapshot = {"state": "reading", "items": [answer()], "height": 100, "scroll_y": 0}
    session.consume(snapshot, 0)
    session.consume({"state": "needs_login", "items": [answer("2")]}, 50)
    assert session.status == "needs_login" and len(session.items) == 1
    session.consume(snapshot, 500)
    assert session.status == "running"
    session.consume(snapshot, 514)
    assert session.status == "running"
    session.finish("cancelled")
    session.consume({"state": "reading", "items": [answer("2")]}, 600)
    session.finish("ready")
    assert read_result(path)["status"] == "cancelled"
    assert len(read_result(path)["items"]) == 1


def test_partial_ready_after_stable_loaded_page(request_file):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    snapshot = {"state": "reading", "items": [answer()], "height": 100, "scroll_y": 0}
    session.consume(snapshot, 0)
    session.consume(snapshot | {"scroll_y": 20}, 14)
    session.consume(snapshot | {"scroll_y": 20}, 28)
    assert session.status == "running"
    session.consume(snapshot | {"scroll_y": 20}, 29)
    assert session.status == "ready"
    assert len(session.items) == 1


def test_twenty_maximum_chinese_bodies_fit_without_truncation(request_file):
    path, request = request_file
    session = browser.QuestionReadSession(path, request | {"count": 20})
    session.consume(
        {"state": "reading", "items": [answer(str(i), text="中" * 100000) for i in range(20)]}, 0
    )
    result = read_result(path)
    assert result["status"] == "ready" and len(result["items"]) == 20
    assert all(len(item["text"]) == 100000 for item in result["items"])
    assert (path / "result.json").stat().st_size < browser.MAX_RESULT_BYTES


def test_later_longer_body_replaces_preview_and_restarts_stability(request_file):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    short = {"state": "reading", "items": [answer(text="已加载第一段")], "height": 100}
    longer = short | {"items": [answer(text="已加载第一段\n后来完成加载的第二段")]}
    session.consume(short, 0)
    session.consume(longer, 14)
    session.consume(longer, 28)
    assert session.status == "running"
    session.consume(longer, 29)
    assert session.status == "ready"
    assert read_result(path)["items"][0]["text"] == longer["items"][0]["text"]


def test_atomic_terminal_retries_transient_windows_reader(request_file, monkeypatch):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    replace = Path.replace
    attempts = []

    def busy_twice(temporary, target):
        attempts.append(temporary)
        if len(attempts) <= 2:
            raise PermissionError("synthetic reader lock")
        return replace(temporary, target)

    monkeypatch.setattr(Path, "replace", busy_twice)
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    session.finish("ready")
    assert len(attempts) == 3
    assert session.status == read_result(path)["status"] == "ready"


def test_failed_terminal_write_remains_retryable(request_file, monkeypatch):
    path, request = request_file
    session = browser.QuestionReadSession(path, request)
    replace = Path.replace
    monkeypatch.setattr(
        Path, "replace", lambda *_: (_ for _ in ()).throw(PermissionError("synthetic"))
    )
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        session.finish("ready")
    assert session.status == read_result(path)["status"] == "running"
    monkeypatch.setattr(Path, "replace", replace)
    session.finish("ready")
    assert session.status == read_result(path)["status"] == "ready"
    assert not list(path.glob("*.tmp"))


@pytest.mark.parametrize(
    "change",
    [
        {"count": True},
        {"count": 21},
        {"parent_pid": -1},
        {"profile_dir": "relative"},
        {"url": "https://example.test/question/123"},
    ],
)
def test_request_rejects_invalid_parameters_without_leaking_them(request_file, change):
    path, request = request_file
    (path / "request.json").write_text(json.dumps(request | change), encoding="utf-8")
    assert browser.run_question_browser(path) == 1
    assert read_result(path) == {
        "status": "failed",
        "message": browser.MESSAGES["failed"],
        "items": [],
    }


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


@pytest.mark.parametrize(
    "action",
    ["read", "cancel_flag", "parent_exit", "menu_cancel", "menu_finish", "closed", "write_error"],
)
def test_window_lifecycle_uses_no_api_and_stops_owned_window(request_file, monkeypatch, action):
    path, request = request_file
    signals = {"alive": True, "closed": False, "evaluations": 0}
    calls = {}
    kernel = SimpleNamespace(
        WaitForSingleObject=lambda *_: 258 if signals["alive"] else 0,
        CloseHandle=lambda handle: calls.update(handle_closed=handle),
    )
    monkeypatch.setattr(browser, "_parent_handle", lambda pid: (kernel, 987))
    monkeypatch.setattr(browser, "POLL_SECONDS", 0.01)

    class Window:
        events = SimpleNamespace(loaded=Event(), closed=Event())

        def evaluate_js(self, script):
            assert "__ZHIHU_READER_REQUEST__" not in script
            signals["evaluations"] += 1
            if action == "write_error":
                monkeypatch.setattr(
                    Path,
                    "replace",
                    lambda *_: (_ for _ in ()).throw(PermissionError("synthetic persistent lock")),
                )
            return {
                "state": "reading",
                "items": [answer(), answer("2")] if action == "read" else [answer()],
            }

        def destroy(self):
            signals["closed"] = True
            self.events.closed.fire()

        def load_url(self, target):
            calls["navigation"] = target

    window = Window()

    def create(*args, **kwargs):
        calls.update(kwargs)
        return window

    def start(callback, **kwargs):
        calls["start"] = kwargs
        window.events.loaded.fire()
        callback()
        deadline = time.monotonic() + 3
        while not signals["evaluations"] and time.monotonic() < deadline:
            time.sleep(0.01)
        if action == "cancel_flag":
            (path / "cancel.flag").touch()
        elif action == "parent_exit":
            signals["alive"] = False
        elif action.startswith("menu_"):
            menu = calls["menu"][0]
            next(
                item
                for item in menu.items
                if item.title == ("取消" if action == "menu_cancel" else "完成读取")
            ).function()
        elif action == "closed":
            window.destroy()
        while not signals["closed"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert signals["closed"]

    monkeypatch.setitem(
        sys.modules, "webview", SimpleNamespace(settings={}, create_window=create, start=start)
    )
    monkeypatch.setitem(
        sys.modules,
        "webview.menu",
        SimpleNamespace(
            Menu=lambda title, items: SimpleNamespace(title=title, items=items),
            MenuAction=lambda title, function: SimpleNamespace(title=title, function=function),
        ),
    )
    assert browser.run_question_browser(path) == (1 if action == "write_error" else 0)
    assert calls["js_api"] is None and calls["on_top"] is False
    assert calls["start"]["private_mode"] is False
    assert calls["start"]["storage_path"] == request["profile_dir"]
    assert calls["handle_closed"] == 987
    if action == "write_error":
        # The manager can now detect the exited worker; it must not run forever on a locked file.
        assert read_result(path)["status"] == "running"
        return
    assert read_result(path)["status"] == (
        "ready" if action in {"read", "menu_finish"} else "cancelled"
    )
    assert read_result(path)["items"]
