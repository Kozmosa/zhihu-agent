"""Own bounded browser collection jobs and validate their local output files."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from zhijing.core.errors import DomainError
from zhijing.domain.models import SourceDraft
from zhijing.features.zhihu.question_models import collection_target, raw_answer_to_draft

MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_DURATION_SECONDS = 10 * 60
TERMINAL = {"ready", "failed", "cancelled"}
STATUSES = {"running", "needs_login", *TERMINAL}


class _ProfileLock:
    """An OS lock also prevents two service instances sharing the browser profile."""

    def __init__(self, path: Path):
        self.file = path.open("a+b")
        try:
            if self.file.tell() == 0:
                self.file.write(b"\0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise DomainError(
                "zhihu_question_busy",
                "已有知乎读取窗口正在使用登录状态，请先完成或取消当前任务。",
                409,
            ) from None

    def close(self):
        if not self.file.closed:
            try:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close()


@dataclass
class _Job:
    id: str
    url: str
    count: int
    directory: Path
    process: subprocess.Popen
    profile_lock: _ProfileLock | None
    started: float = field(default_factory=time.monotonic)
    status: str = "running"
    items: dict[str, SourceDraft] = field(default_factory=dict)
    fingerprint: tuple[int, int] | None = None
    skipped: bool = False
    reason: str = ""
    stop_requested: bool = False
    timer: threading.Timer | None = None


class QuestionJobs:
    def __init__(self, data_dir: Path, project_root: Path):
        self.data_dir = Path(data_dir).resolve()
        self.project_root = Path(project_root).resolve()
        self._jobs: dict[str, _Job] = {}
        self._active_id: str | None = None
        self._lock = threading.RLock()
        self._closed = False

    def start(self, url: str, count: int = 10) -> dict:
        try:
            normalized = collection_target(url)["url"]
            if type(count) is not int or not 1 <= count <= 20:
                raise ValueError("Invalid count")
        except (ValueError, TypeError):
            raise DomainError(
                "invalid_zhihu_question",
                "请输入有效的知乎问题或作者主页链接，读取数量为 1 到 20 条。",
                422,
            ) from None
        with self._lock:
            if self._closed:
                raise DomainError(
                    "zhihu_question_closed", "知乎读取服务正在退出，请重新打开知境。", 503
                )
            if self._active_id:
                self._refresh(self._jobs[self._active_id])
            if self._active_id:
                raise DomainError(
                    "zhihu_question_busy",
                    "已有知乎读取窗口正在使用登录状态，请先完成或取消当前任务。",
                    409,
                )
            root = self.data_dir / "zhihu-question-jobs"
            profile_lock = None
            try:
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                profile_lock = _ProfileLock(root / "profile.lock")
                job_id = uuid.uuid4().hex
                directory = root / job_id
                directory.mkdir(mode=0o700)
                request = {
                    "url": normalized,
                    "count": count,
                    "parent_pid": os.getpid(),
                    "profile_dir": str(self.data_dir / "zhihu-browser"),
                }
                with (directory / "request.json").open("x", encoding="utf-8") as output:
                    json.dump(request, output, ensure_ascii=False)
                (directory / "request.json").chmod(0o600)
                command = [sys.executable]
                if not getattr(sys, "frozen", False):
                    command += ["-s", "-B", str(self.project_root / "desktop.py")]
                command += ["--zhihu-collect-job", str(directory)]
                environment = os.environ.copy()
                for name in tuple(environment):
                    if name.startswith(("ZHIJING_OPENAI_", "ZHIJING_OLLAMA_")) or name in {
                        "ZHIHU_ACCESS_SECRET",
                        "OPENAI_API_KEY",
                        "OLLAMA_API_KEY",
                    }:
                        environment.pop(name, None)
                environment["PYTHONNOUSERSITE"] = "1"
                environment["PYTHONDONTWRITEBYTECODE"] = "1"
                process = subprocess.Popen(
                    command,
                    cwd=self.project_root,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception as error:
                if profile_lock is not None:
                    profile_lock.close()
                if isinstance(error, DomainError):
                    raise
                raise DomainError(
                    "zhihu_question_start_failed",
                    "知乎读取窗口未能启动，请检查软件组件和资料目录权限。",
                    503,
                ) from None
            job = _Job(job_id, normalized, count, directory, process, profile_lock)
            self._jobs[job_id] = job
            self._active_id = job_id
            job.timer = threading.Timer(MAX_DURATION_SECONDS, self._expire, args=(job_id,))
            job.timer.daemon = True
            job.timer.start()
            # Keep bounded in-memory previews; files remain local and are never served as assets.
            while len(self._jobs) > 32:
                oldest = next(iter(self._jobs))
                if oldest == self._active_id:
                    break
                self._jobs.pop(oldest)
            return self._view(job)

    def _lookup(self, job_id: str) -> _Job:
        if not isinstance(job_id, str) or job_id not in self._jobs:
            raise DomainError("zhihu_question_not_found", "未找到该知乎读取任务，请重新开始。", 404)
        return self._jobs[job_id]

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._lookup(job_id)
            self._refresh(job)
            return self._view(job)

    def _read_result(self, job: _Job):
        path = job.directory / "result.json"
        try:
            info = path.stat()
        except FileNotFoundError:
            return
        fingerprint = (info.st_mtime_ns, info.st_size)
        if fingerprint == job.fingerprint:
            return
        if path.is_symlink() or info.st_size > MAX_RESULT_BYTES:
            raise ValueError("Invalid job result")
        with path.open("rb") as source:
            content = source.read(MAX_RESULT_BYTES + 1)
        if len(content) > MAX_RESULT_BYTES:
            raise ValueError("Oversized job result")
        data = json.loads(content.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or data.get("status") not in STATUSES
            or not isinstance(data.get("items"), list)
            or len(data["items"]) > 20
        ):
            raise ValueError("Invalid job result")
        for raw in data["items"]:
            try:
                draft = raw_answer_to_draft(raw, job.url)
            except (ValueError, TypeError):
                job.skipped = True
                continue
            key = draft.provenance.external_id
            if key in job.items or len(job.items) < job.count:
                job.items[key] = draft
        job.fingerprint = fingerprint
        job.status = data["status"]

    def _refresh(self, job: _Job):
        if job.status not in TERMINAL:
            try:
                self._read_result(job)
            except (OSError, ValueError, TypeError, RecursionError):
                job.status, job.reason = "failed", "invalid_result"
                self._stop_process(job)
        returncode = job.process.poll()
        if returncode is not None:
            # A worker may publish its final snapshot between the earlier read and poll.
            if job.status not in TERMINAL:
                try:
                    self._read_result(job)
                except (OSError, ValueError, TypeError, RecursionError):
                    job.status, job.reason = "failed", "invalid_result"
            if job.status not in TERMINAL or (
                returncode != 0 and not job.stop_requested and job.status == "ready"
            ):
                job.status, job.reason = "failed", "worker_exit"
            self._release(job)
        elif time.monotonic() - job.started >= MAX_DURATION_SECONDS:
            if job.status not in TERMINAL:
                job.status, job.reason = "failed", "timeout"
            self._stop_process(job)

    def _expire(self, job_id: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                self._refresh(job)

    def _release(self, job: _Job):
        if job.timer is not None:
            job.timer.cancel()
        if job.profile_lock is not None:
            job.profile_lock.close()
            job.profile_lock = None
        if self._active_id == job.id:
            self._active_id = None

    def _stop_process(self, job: _Job):
        job.stop_requested = True
        if job.process.poll() is None:
            try:
                (job.directory / "cancel.flag").touch(mode=0o600)
                job.process.wait(timeout=1.2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    job.process.terminate()
                    job.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        job.process.kill()
                        job.process.wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
        if job.process.poll() is not None:
            self._release(job)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._lookup(job_id)
            self._refresh(job)
            if job.status not in TERMINAL:
                job.status = "cancelled"
            self._stop_process(job)
            return self._view(job)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for job in self._jobs.values():
                if job.status not in TERMINAL:
                    job.status = "cancelled"
                self._stop_process(job)

    @staticmethod
    def _view(job: _Job) -> dict:
        count = len(job.items)
        if job.status == "running":
            message = f"正在读取页面中的回答，已读取 {count} 条。"
        elif job.status == "needs_login":
            message = (
                f"请在知乎读取窗口完成登录或页面验证，已读取 {count} 条；知境不会读取登录凭据。"
            )
        elif job.status == "ready":
            message = (
                f"已读取 {count} 条回答，请预览正文后选择导入。"
                if count
                else "当前页面没有读取到可导入的回答，请检查页面后重试。"
            )
        elif job.status == "cancelled":
            message = f"读取已取消，保留 {count} 条已读取回答供预览。"
        elif job.reason == "timeout":
            message = f"读取已超过 10 分钟并停止，保留 {count} 条已读取回答供预览。"
        elif job.reason == "invalid_result":
            message = f"读取窗口返回的内容无效或过大，已停止；保留 {count} 条回答供预览。"
        else:
            message = f"读取窗口未能正常完成任务，保留 {count} 条已读取回答供预览。"
        if job.skipped:
            message += " 部分回答因来源或正文无效已跳过。"
        return {
            "id": job.id,
            "status": job.status,
            "question_url": job.url,
            "requested_count": job.count,
            "collected_count": count,
            "message": message,
            "items": [draft.model_dump(mode="json") for draft in job.items.values()],
            "terminal": job.status in TERMINAL,
            "mode": collection_target(job.url)["mode"],
        }
