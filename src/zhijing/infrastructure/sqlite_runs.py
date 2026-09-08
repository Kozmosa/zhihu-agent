"""Short SQLite transactions persist each step independently of model execution."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from zhijing.core.errors import DomainError
from zhijing.features.runs.schemas import RunError, RunPage, RunRecord, RunStatus, RunSummary


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteRunRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 0xFF in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }:
                raise DomainError("storage_busy", "工作流存储暂时繁忙，请稍后重试。", 503) from exc
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Initialization is also used when switching model configuration. Recovery is
        # deliberately separate and must run only at the single process's startup.
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        finally:
            connection.close()
        with self._connection(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, "
                "request_hash TEXT NOT NULL, source_id TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL, "
                "summary TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_source ON runs(source_id)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at, id)"
            )

    @staticmethod
    def _summary(run: RunRecord) -> str:
        return RunSummary(
            id=run.id,
            source_id=run.request.source_id,
            status=run.status,
            tasks=run.request.tasks,
            succeeded_steps=sum(step.status == "succeeded" for step in run.steps),
            total_steps=len(run.steps),
            attempts=run.attempts,
            provider=run.provider,
            model=run.model,
            cancel_requested=run.cancel_requested,
            created_at=run.created_at,
            updated_at=run.updated_at,
            finished_at=run.finished_at,
        ).model_dump_json()

    def create_or_get(
        self, run: RunRecord, key_hash: str, request_hash: str
    ) -> tuple[RunRecord, bool]:
        with self._connection(write=True) as connection:
            row = connection.execute(
                "SELECT request_hash, payload FROM runs WHERE key_hash = ?", (key_hash,)
            ).fetchone()
            if row:
                if row[0] != request_hash:
                    raise DomainError(
                        "idempotency_conflict", "该幂等键已用于不同的请求，请使用新的键。", 409
                    )
                return RunRecord.model_validate_json(row[1]), False
            connection.execute(
                "INSERT INTO runs "
                "(id, key_hash, request_hash, source_id, status, created_at, summary, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    key_hash,
                    request_hash,
                    run.request.source_id,
                    run.status,
                    run.created_at,
                    self._summary(run),
                    run.model_dump_json(),
                ),
            )
        return run, True

    @staticmethod
    def _load(connection, run_id: str) -> RunRecord:
        row = connection.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise DomainError("run_not_found", "未找到指定工作流。", 404)
        return RunRecord.model_validate_json(row[0])

    def get(self, run_id: str) -> RunRecord:
        with self._connection() as connection:
            return self._load(connection, run_id)

    def _save(self, connection, run: RunRecord) -> None:
        run.updated_at = _now()
        connection.execute(
            "UPDATE runs SET status = ?, summary = ?, payload = ? WHERE id = ?",
            (run.status, self._summary(run), run.model_dump_json(), run.id),
        )

    def mutate(self, run_id: str, change: Callable[[RunRecord], None]) -> RunRecord:
        with self._connection(write=True) as connection:
            run = self._load(connection, run_id)
            change(run)
            self._save(connection, run)
        return run

    def list(
        self,
        offset: int = 0,
        limit: int = 20,
        source_id: str | None = None,
        status: RunStatus | None = None,
    ) -> RunPage:
        if offset < 0 or offset > 2**63 - 1 or not 1 <= limit <= 100:
            raise DomainError("invalid_pagination", "分页参数超出允许范围。", 422)
        clauses, params = [], []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as connection:
            total = connection.execute("SELECT COUNT(*) FROM runs" + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT summary FROM runs" + where + " ORDER BY created_at DESC, id DESC "
                "LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items = [RunSummary.model_validate_json(row[0]) for row in rows]
        return RunPage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < total,
        )

    def recover_interrupted(self) -> int:
        with self._connection(write=True) as connection:
            rows = connection.execute(
                "SELECT payload FROM runs WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                run = RunRecord.model_validate_json(row[0])
                run.status = "interrupted"
                run.finished_at = _now()
                for step in run.steps:
                    if step.status == "running":
                        step.status = "interrupted"
                        step.finished_at = run.finished_at
                        step.error = RunError(
                            code="process_interrupted",
                            message="上次执行意外中断，可重试未完成步骤。",
                        )
                self._save(connection, run)
        return len(rows)
