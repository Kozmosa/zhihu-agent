"""Bounded browser jobs use synthetic local files and owned process fakes only."""

import hashlib
import json
import os
import subprocess
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.features.zhihu import question_jobs
from zhijing.features.zhihu.question_jobs import QuestionJobs
from zhijing.features.zhihu.question_models import (
    collection_target,
    normalize_author_url,
    normalize_question_url,
    question_id_from_url,
    raw_answer_to_draft,
)
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository

QUESTION = "https://www.zhihu.com/question/123456"
CANARY = "synthetic-secret-must-not-appear-in-errors"


@pytest.mark.parametrize("suffix", ["", "/", "/answers", "/answers/?utm_source=test"])
def test_author_profile_normalization(suffix):
    assert (
        normalize_author_url("https://www.zhihu.com/people/example-author" + suffix)
        == "https://www.zhihu.com/people/example-author/answers"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/people/a",
        "https://www.zhihu.com/people/a/followers",
        "https://user:secret@www.zhihu.com/people/a",
        "https://www.zhihu.com:444/people/a",
    ],
)
def test_author_target_rejects_unsupported_or_unsafe_urls(url):
    with pytest.raises(ValueError):
        collection_target(url)


def test_author_collection_accepts_cross_question_answers_but_rejects_other_or_unknown_authors(
    jobs,
):
    manager, processes, _ = jobs
    view = manager.start("https://www.zhihu.com/people/example-author", 10)
    assert view["mode"] == "author"
    first = answer()
    other_question = answer(
        "900",
        question_id="456",
        url="https://www.zhihu.com/question/456/answer/900",
        title="另一个问题？",
    )
    write_result(
        manager,
        view["id"],
        "ready",
        [
            first,
            other_question,
            answer("901", author_url="https://www.zhihu.com/people/same-nickname"),
            answer("902", author_url=""),
        ],
    )
    processes[0].returncode = 0
    result = manager.status(view["id"])
    assert result["collected_count"] == 2
    assert {item["title"] for item in result["items"]} == {first["title"], "另一个问题？"}
    assert {item["author_id"] for item in result["items"]} == {"zhihu-author:people:example-author"}
    assert "跳过" in result["message"]


def answer(answer_id="789", **updates):
    return {
        "answer_id": answer_id,
        "question_id": "123456",
        "title": "如何理解主动回忆？",
        "author_name": "测试作者",
        "author_url": "https://www.zhihu.com/people/example-author",
        "text": "主动回忆通过主动提取知识帮助学习。\n普通比较 a < b 应保留。",
        "url": f"{QUESTION}/answer/{answer_id}",
        **updates,
    }


class FakeProcess:
    def __init__(self, command, **options):
        self.command = command
        self.options = options
        self.returncode = None
        self.waits = []
        self.terminated = False
        self.killed = False
        self.ignores_cancel = False
        self.ignores_terminate = False

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.returncode is None:
            if self.ignores_cancel:
                raise subprocess.TimeoutExpired("owned-browser", timeout)
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.ignores_terminate:
            self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


class FakeTimer:
    def __init__(self, interval, function, args):
        self.interval, self.function, self.args = interval, function, args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function(*self.args)


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    processes, timers = [], []

    def spawn(command, **options):
        process = FakeProcess(command, **options)
        processes.append(process)
        return process

    def timer(interval, function, args):
        instance = FakeTimer(interval, function, args)
        timers.append(instance)
        return instance

    monkeypatch.setattr(question_jobs.subprocess, "Popen", spawn)
    monkeypatch.setattr(question_jobs.threading, "Timer", timer)
    monkeypatch.setattr(question_jobs.sys, "frozen", False, raising=False)
    manager = QuestionJobs(tmp_path / "data", tmp_path / "project")
    try:
        yield manager, processes, timers
    finally:
        manager.close()


def write_result(manager, job_id, status="running", items=None, **changes):
    directory = manager.data_dir / "zhihu-question-jobs" / job_id
    payload = {"status": status, "message": CANARY, "items": items or [], **changes}
    temporary = directory / "result.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(directory / "result.json")


@pytest.mark.parametrize(
    "url",
    [QUESTION, QUESTION + "/?utm_source=fixture#answer", "http://m.zhihu.com/question/123456"],
)
def test_question_link_normalizes_official_variants(url):
    assert normalize_question_url(url) == QUESTION
    assert question_id_from_url(url) == "123456"


@pytest.mark.parametrize(
    "url",
    [
        "https://outside.test/question/123456",
        "https://www.zhihu.com.evil.test/question/123456",
        "https://user:secret@www.zhihu.com/question/123456",
        "https://www.zhihu.com:444/question/123456",
        "https://www.zhihu.com/question/123456/answer/789",
        "https://www.zhihu.com/question/１２３",
        "https://www.zhihu.com/question/%31%32%33",
        "file:///question/123456",
    ],
)
def test_question_link_rejects_other_destinations_and_non_question_paths(url):
    with pytest.raises(ValueError):
        normalize_question_url(url)


def test_answer_mapping_retains_text_and_traceability_and_reimport_is_idempotent(tmp_path):
    draft = raw_answer_to_draft(answer(url=QUESTION + "/answer/789?utm_source=first"), QUESTION)
    assert draft.origin == "zhihu" and draft.content_extent == "unknown"
    assert draft.text == answer()["text"]
    assert str(draft.url) == QUESTION + "/answer/789"
    assert draft.author_id == "zhihu-author:people:example-author"
    assert draft.provenance.external_author_id == "people:example-author"
    assert draft.provenance.external_id == "789"
    assert draft.provenance.content_hash == hashlib.sha256(draft.text.encode("utf-8")).hexdigest()
    assert draft.provenance.fetched_at.utcoffset().total_seconds() == 0
    repeated = raw_answer_to_draft(answer(url=QUESTION + "/answer/789?utm_source=second"), QUESTION)
    repeated.provenance.fetched_at = draft.provenance.fetched_at + timedelta(days=1)
    repository = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    repository.initialize()
    first = repository.save(draft)
    assert repository.save(repeated) == first
    assert len(repository.list()) == 1


@pytest.mark.parametrize("author_url", [None, "https://outside.test/people/someone", QUESTION])
def test_unknown_author_identity_is_scoped_to_answer(author_url):
    first = raw_answer_to_draft(answer(author_url=author_url, author_name=""), QUESTION)
    second = raw_answer_to_draft(answer("790", author_url=author_url), QUESTION)
    assert first.author_name == "未知作者"
    assert first.author_id == "zhihu-content:answer:789"
    assert first.author_id != second.author_id
    assert first.provenance.external_author_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"question_id": "999"},
        {"answer_id": "-789"},
        {"answer_id": 789},
        {"url": QUESTION + "/answer/790"},
        {"url": "https://outside.test/question/123456/answer/789"},
        {"text": " "},
        {"text": "文" * 100_001},
        {"text": "body\0secret"},
        {"title": {"unsafe": "value"}},
    ],
)
def test_answer_mapping_rejects_wrong_identity_or_invalid_body(changes):
    with pytest.raises(ValueError):
        raw_answer_to_draft(answer(**changes), QUESTION)


def test_construct_is_lazy_and_start_writes_only_private_request_and_owned_command(
    jobs, monkeypatch
):
    manager, processes, timers = jobs
    assert not manager.data_dir.exists() and not timers
    for key in ("ZHIHU_ACCESS_SECRET", "ZHIJING_OPENAI_API_KEY", "ZHIJING_OLLAMA_API_KEY"):
        monkeypatch.setenv(key, CANARY)
    job = manager.start(QUESTION + "?secret=" + CANARY, 3)
    assert job["status"] == "running" and not job["terminal"] and not job["items"]
    assert job["collected_count"] == 0 and job["requested_count"] == 3
    directory = manager.data_dir / "zhihu-question-jobs" / job["id"]
    request_text = (directory / "request.json").read_text("utf-8")
    request = json.loads(request_text)
    assert request == {
        "url": QUESTION,
        "count": 3,
        "parent_pid": os.getpid(),
        "profile_dir": str(manager.data_dir / "zhihu-browser"),
    }
    assert CANARY not in request_text + json.dumps(job)
    process = processes[0]
    assert process.command[:4] == [
        question_jobs.sys.executable,
        "-s",
        "-B",
        str(manager.project_root / "desktop.py"),
    ]
    assert process.command[-2:] == ["--zhihu-collect-job", str(directory)]
    assert (
        process.options["stdin"]
        == process.options["stdout"]
        == process.options["stderr"]
        == subprocess.DEVNULL
    )
    assert CANARY not in json.dumps(process.options["env"])
    assert len(timers) == 1 and timers[0].started and timers[0].daemon
    assert timers[0].interval == 600
    assert not list(manager.data_dir.rglob("*.sqlite3")), "Jobs must not auto-import answers"


def test_frozen_worker_launch_has_no_source_script(jobs, monkeypatch):
    manager, processes, _ = jobs
    monkeypatch.setattr(question_jobs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(question_jobs.sys, "executable", str(manager.project_root / "知境.exe"))
    manager.start(QUESTION)
    assert processes[0].command[0].endswith("知境.exe")
    assert processes[0].command[1] == "--zhihu-collect-job"
    assert len(processes[0].command) == 3


def test_profile_is_busy_across_managers_until_owned_process_exits(jobs):
    manager, processes, _ = jobs
    first = manager.start(QUESTION)
    other = QuestionJobs(manager.data_dir, manager.project_root)
    try:
        with pytest.raises(DomainError) as blocked:
            manager.start(QUESTION)
        assert blocked.value.status == 409
        with pytest.raises(DomainError) as blocked:
            other.start(QUESTION)
        assert blocked.value.status == 409
        write_result(manager, first["id"], "ready", [answer()])
        assert manager.status(first["id"])["terminal"]
        with pytest.raises(DomainError):
            manager.start(QUESTION)
        processes[0].returncode = 0
        assert manager.status(first["id"])["status"] == "ready"
        assert other.start(QUESTION)["status"] == "running"
    finally:
        other.close()


def test_progress_deduplicates_filters_and_preserves_partial_items_on_worker_exit(jobs):
    manager, processes, _ = jobs
    job_id = manager.start(QUESTION, 2)["id"]
    write_result(manager, job_id, "needs_login", [answer()])
    progress = manager.status(job_id)
    assert progress["status"] == "needs_login" and progress["collected_count"] == 1
    assert CANARY not in json.dumps(progress, ensure_ascii=False)
    write_result(
        manager,
        job_id,
        items=[answer(), answer(), answer("790"), answer("791"), answer("792", question_id="999")],
    )
    assert manager.status(job_id)["collected_count"] == 2
    processes[0].returncode = 1
    failed = manager.status(job_id)
    assert failed["status"] == "failed" and failed["terminal"]
    assert failed["collected_count"] == 2 and "跳过" in failed["message"]
    assert [row["provenance"]["external_id"] for row in failed["items"]] == ["789", "790"]


@pytest.mark.parametrize(
    "contents",
    [
        b"not json " + CANARY.encode(),
        b'{"status":[],"items":[]}',
        b"x" * (question_jobs.MAX_RESULT_BYTES + 1),
    ],
    ids=["invalid-json", "invalid-status", "oversized"],
)
def test_invalid_output_fails_safely_without_losing_previous_preview(jobs, contents):
    manager, processes, _ = jobs
    job_id = manager.start(QUESTION)["id"]
    write_result(manager, job_id, items=[answer()])
    assert manager.status(job_id)["collected_count"] == 1
    (manager.data_dir / "zhihu-question-jobs" / job_id / "result.json").write_bytes(contents)
    result = manager.status(job_id)
    assert result["status"] == "failed" and result["collected_count"] == 1
    assert CANARY not in json.dumps(result)
    assert processes[0].poll() is not None


def test_twenty_long_chinese_answers_fit_the_result_budget(jobs):
    manager, processes, _ = jobs
    job_id = manager.start(QUESTION, 20)["id"]
    items = [answer(str(1000 + index), text="文" * 100_000) for index in range(20)]
    write_result(manager, job_id, "ready", items)
    result_file = manager.data_dir / "zhihu-question-jobs" / job_id / "result.json"
    assert 3 * 1024 * 1024 < result_file.stat().st_size < question_jobs.MAX_RESULT_BYTES
    processes[0].returncode = 0
    result = manager.status(job_id)
    assert result["status"] == "ready" and result["collected_count"] == 20
    assert all(len(item["text"]) == 100_000 for item in result["items"])


def test_final_snapshot_published_during_exit_poll_is_not_lost(jobs, monkeypatch):
    manager, processes, _ = jobs
    job_id = manager.start(QUESTION)["id"]

    def exit_after_publishing():
        write_result(manager, job_id, "ready", [answer()])
        return 0

    monkeypatch.setattr(processes[0], "poll", exit_after_publishing)
    result = manager.status(job_id)
    assert result["status"] == "ready"
    assert result["collected_count"] == 1


def test_empty_completed_page_is_not_reported_as_collected_content(jobs):
    manager, processes, _ = jobs
    job_id = manager.start(QUESTION)["id"]
    write_result(manager, job_id, "ready")
    processes[0].returncode = 0
    result = manager.status(job_id)
    assert result["terminal"] and result["items"] == []
    assert result["collected_count"] == 0
    assert "没有读取到" in result["message"]


def test_expiry_without_polling_stops_only_owned_process_and_keeps_preview(jobs):
    manager, processes, timers = jobs
    job_id = manager.start(QUESTION)["id"]
    write_result(manager, job_id, items=[answer()])
    manager._jobs[job_id].started -= 601
    processes[0].ignores_cancel = True
    unrelated = FakeProcess([])
    timers[0].fire()
    result = manager.status(job_id)
    assert result["status"] == "failed" and "10 分钟" in result["message"]
    assert result["collected_count"] == 1
    assert processes[0].terminated and not unrelated.terminated
    assert timers[0].cancelled


def test_cancel_and_close_are_idempotent_and_release_owned_processes(jobs):
    manager, processes, timers = jobs
    job_id = manager.start(QUESTION)["id"]
    processes[0].ignores_cancel = processes[0].ignores_terminate = True
    result = manager.cancel(job_id)
    assert result["status"] == "cancelled" and result["terminal"]
    assert (manager.data_dir / "zhihu-question-jobs" / job_id / "cancel.flag").exists()
    assert processes[0].terminated and processes[0].killed
    manager.cancel(job_id)
    manager.start(QUESTION)
    manager.close()
    manager.close()
    assert all(process.poll() is not None for process in processes)
    assert all(timer.cancelled for timer in timers)
    with pytest.raises(DomainError) as closed:
        manager.start(QUESTION)
    assert closed.value.status == 503


def test_start_failure_is_sanitized_and_releases_profile_lock(jobs, monkeypatch):
    manager, _, _ = jobs
    original = question_jobs.subprocess.Popen

    def fail(*args, **kwargs):
        raise OSError(CANARY)

    monkeypatch.setattr(question_jobs.subprocess, "Popen", fail)
    with pytest.raises(DomainError) as failed:
        manager.start(QUESTION)
    assert failed.value.status == 503 and CANARY not in str(failed.value)
    monkeypatch.setattr(question_jobs.subprocess, "Popen", original)
    assert manager.start(QUESTION)["status"] == "running"


def test_question_job_routes_require_guard_and_do_not_echo_invalid_input(jobs, tmp_path):
    manager, processes, _ = jobs
    with TestClient(
        create_app(Settings(data_dir=tmp_path / "api")),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        client.app.state.zhihu_questions = manager
        base = "/api/v1/zhihu/questions/jobs"
        assert client.post(base, json={"url": QUESTION}).status_code == 403
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        assert (
            client.post(
                base, json={"url": QUESTION}, headers={"Origin": "https://outside.test"}
            ).status_code
            == 403
        )
        invalid = client.post(base, json={"url": "https://outside.test/" + CANARY, "count": 0})
        assert invalid.status_code == 422 and CANARY not in invalid.text
        invalid = client.post(base, json={"url": "https://outside.test/" + CANARY, "count": 1})
        assert invalid.status_code == 422 and CANARY not in invalid.text
        assert client.post(base, json={"url": QUESTION, "count": True}).status_code == 422
        assert not processes
        started = client.post(base, json={"url": QUESTION, "count": 3})
        assert started.status_code == 200 and started.headers["cache-control"] == "no-store"
        job_id = started.json()["id"]
        assert client.get(base + "/" + job_id).json()["requested_count"] == 3
        assert client.get(base + "/not-a-job").status_code == 404
        client.headers.pop("X-Zhijing-Token")
        assert client.post(base + "/" + job_id + "/cancel").status_code == 403
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        cancelled = client.post(base + "/" + job_id + "/cancel")
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    with TestClient(
        create_app(Settings(data_dir=tmp_path / "remote")), client=("192.0.2.2", 12345)
    ) as client:
        assert client.get(base + "/anything").status_code == 403
