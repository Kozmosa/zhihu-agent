"""Synchronous, durable runs with per-step commits and cooperative controls."""

import hashlib
import json
import re
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from zhijing.core.errors import DomainError
from zhijing.features.companion.schemas import TASK_ORDER, CompanionResult
from zhijing.features.companion.service import CompanionService
from zhijing.features.runs.ports import RunRepository
from zhijing.features.runs.schemas import RunError, RunRecord, RunRequest, RunStep
from zhijing.features.runs.snapshot import SourceSnapshot


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _ControlStop(Exception):
    def __init__(self, status: str):
        self.status = status


def _safe_error(exc: Exception) -> RunError:
    # Never persist str(exc), upstream bodies, endpoint URLs, or provider error text.
    messages = {
        "model_unavailable": "模型暂不可用，请检查连接或配置后重试。",
        "model_timeout": "模型调用超时，请检查服务或调整传输超时后重试。",
        "model_invalid_response": "模型结果未通过结构或证据校验。",
        "model_input_too_large": "输入超出当前模型处理预算，请调整配置后重试。",
        "model_batch_limit": "所需模型批次数超出上限，请缩小资料范围或调整输入预算。",
        "source_not_found": "工作流快照中的资料已不可用。",
        "storage_busy": "资料库暂时繁忙，请稍后重试。",
    }
    code = exc.code if isinstance(exc, DomainError) and exc.code in messages else "step_failed"
    return RunError(
        code=code,
        message=messages.get(code, "该步骤执行失败，可检查配置后重试。"),
        retryable=code not in {"source_not_found", "model_input_too_large", "model_batch_limit"},
    )


def _model_label(model: str | None) -> str | None:
    if not model:
        return None
    # Model IDs can contain namespaces and colon tags, but credentials and URLs
    # do not belong in the audit metadata, even if accidentally entered as a name.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model) and "://" not in model:
        if not model.lower().startswith(("sk-", "bearer")):
            return model
    return "[redacted]"


class RunService:
    def __init__(
        self,
        repository: RunRepository,
        companion: CompanionService,
        *,
        provider: str = "extractive",
        model: str | None = None,
    ):
        self.repository = repository
        self.companion = companion
        self.provider = provider if provider in {"extractive", "ollama", "openai"} else "other"
        self.model = _model_label(model)

    def recover_interrupted(self) -> int:
        return self.repository.recover_interrupted()

    def get(self, run_id: str) -> RunRecord:
        return self.repository.get(run_id)

    def list(self, offset=0, limit=20, source_id=None, status=None):
        return self.repository.list(offset, limit, source_id, status)

    def create(self, request: RunRequest, idempotency_key: str) -> RunRecord:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", idempotency_key):
            raise DomainError(
                "invalid_idempotency_key", "幂等键须为 1 至 128 个安全 ASCII 字符。", 422
            )
        source = self.companion.validate(request)
        tasks = set(request.tasks)
        if "facts" in tasks or ("knowledge" in tasks and request.knowledge_scope == "library"):
            corpus = self.companion.sources.repository.list()
        elif tasks & {"author", "knowledge"}:
            corpus = self.companion.sources.repository.list(source.author_id)
        else:
            corpus = [source]
        source_ids = sorted({source.id, *(item.id for item in corpus)})
        now = _now()
        run = RunRecord(
            id=uuid4().hex,
            request=request,
            source_ids=source_ids,
            provider=self.provider,
            model=self.model,
            created_at=now,
            updated_at=now,
            steps=[RunStep(task=task) for task in TASK_ORDER if task in tasks],
            result=CompanionResult(source_id=source.id),
        )
        canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        run, created = self.repository.create_or_get(
            run,
            hashlib.sha256(idempotency_key.encode()).hexdigest(),
            hashlib.sha256(canonical.encode()).hexdigest(),
        )
        if not created or request.prepare_only:
            return run
        return self.execute(run.id)

    def execute(self, run_id: str) -> RunRecord:
        return self._execute(run_id, retry=False)

    def retry(self, run_id: str) -> RunRecord:
        return self._execute(run_id, retry=True)

    def _claim(self, run_id: str, retry: bool) -> RunRecord:
        def claim(run):
            if run.status == "running":
                raise DomainError("run_busy", "工作流正在执行，请查询进度。", 409)
            allowed = (
                {"partial", "failed", "interrupted", "cancelled", "timed_out"}
                if retry
                else {"pending"}
            )
            if run.status not in allowed:
                raise DomainError("run_not_executable", "当前状态不允许此执行操作。", 409)
            if run.attempts >= run.request.max_attempts:
                raise DomainError("run_attempts_exhausted", "已达到工作流执行次数上限。", 409)
            if all(step.status == "succeeded" for step in run.steps):
                raise DomainError("run_already_complete", "所有步骤均已完成。", 409)
            run.status = "running"
            run.attempts += 1
            run.cancel_requested = False
            run.started_at = _now()
            run.finished_at = None

        return self.repository.mutate(run_id, claim)

    def _execute(self, run_id: str, *, retry: bool) -> RunRecord:
        run = self._claim(run_id, retry)
        deadline = monotonic() + run.request.timeout_seconds

        def checkpoint():
            if self.repository.get(run_id).cancel_requested:
                raise _ControlStop("cancelled")
            if monotonic() >= deadline:
                raise _ControlStop("timed_out")

        try:
            checkpoint()
            snapshot = SourceSnapshot(self.companion.sources.repository, run.source_ids)
            companion = self.companion.for_repository(snapshot, checkpoint)
        except _ControlStop as stop:
            return self._stop(run_id, stop.status)
        except Exception as exc:
            return self._fail_remaining(run_id, _safe_error(exc))

        for saved_step in run.steps:
            if saved_step.status == "succeeded":
                continue
            task = saved_step.task
            try:
                checkpoint()

                def start_step(current, task=task):
                    step = next(item for item in current.steps if item.task == task)
                    step.status = "running"
                    step.attempts += 1
                    step.provider, step.model = self.provider, self.model
                    step.started_at, step.finished_at, step.error = _now(), None, None

                self.repository.mutate(run_id, start_step)
                result = companion.execute(run.request, task)
                checkpoint()

                def complete_step(current, task=task, result=result):
                    # Validate the typed result before committing either state or data.
                    payload = current.result.model_dump(mode="json")
                    payload[task] = result.model_dump(mode="json")
                    current.result = CompanionResult.model_validate(payload)
                    step = next(item for item in current.steps if item.task == task)
                    step.status, step.finished_at, step.error = "succeeded", _now(), None

                self.repository.mutate(run_id, complete_step)
            except _ControlStop as stop:
                return self._stop(run_id, stop.status)
            except Exception as exc:
                error = _safe_error(exc)

                def fail_step(current, task=task, error=error):
                    step = next(item for item in current.steps if item.task == task)
                    step.status, step.finished_at, step.error = "failed", _now(), error

                self.repository.mutate(run_id, fail_step)
        try:
            checkpoint()
        except _ControlStop as stop:
            return self._stop(run_id, stop.status)
        return self.repository.mutate(run_id, self._finish)

    @staticmethod
    def _finish(run):
        success = sum(step.status == "succeeded" for step in run.steps)
        run.status = (
            "cancelled"
            if run.cancel_requested
            else "succeeded"
            if success == len(run.steps)
            else "partial"
            if success
            else "failed"
        )
        run.finished_at = _now()

    def _fail_remaining(self, run_id: str, error: RunError) -> RunRecord:
        def fail(run):
            for step in run.steps:
                if step.status != "succeeded":
                    step.status, step.finished_at, step.error = "failed", _now(), error
            self._finish(run)

        return self.repository.mutate(run_id, fail)

    def _stop(self, run_id: str, status: str) -> RunRecord:
        def stop(run):
            run.status, run.finished_at = status, _now()
            for step in run.steps:
                if step.status != "succeeded":
                    step.status = "cancelled" if status == "cancelled" else "interrupted"
                    step.finished_at = run.finished_at
                    step.error = RunError(
                        code="run_cancelled" if status == "cancelled" else "run_timeout",
                        message="工作流已取消，可重试未完成步骤。"
                        if status == "cancelled"
                        else "本轮执行预算已用尽，可重试未完成步骤。",
                    )

        return self.repository.mutate(run_id, stop)

    def cancel(self, run_id: str) -> RunRecord:
        def cancel(run):
            if run.status not in {"pending", "running"}:
                return
            run.cancel_requested = True
            if run.status == "pending":
                run.status, run.finished_at = "cancelled", _now()
                for step in run.steps:
                    step.status, step.finished_at = "cancelled", run.finished_at

        return self.repository.mutate(run_id, cancel)
