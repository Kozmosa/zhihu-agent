"""批量导入使用单个事务；分页与搜索在数据库内执行。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source, SourceDraft, SourcePage


class SQLiteSourceRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", 0)
            if code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise DomainError("storage_busy", "资料库暂时繁忙，请稍后重试。", 503) from exc
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sources "
                "(id TEXT PRIMARY KEY, author_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_author ON sources(author_id)")
            connection.execute("PRAGMA user_version=1")

    def save(self, draft: SourceDraft) -> Source:
        return self.save_many([draft])[0]

    def save_many(self, drafts: list[SourceDraft]) -> list[Source]:
        sources = []
        with self._connection() as connection:
            for draft in drafts:
                source = self._prepare(draft)
                connection.execute(
                    "INSERT INTO sources (id, author_id, payload) VALUES (?, ?, ?) "
                    "ON CONFLICT(id) DO NOTHING",
                    (source.id, source.author_id, source.model_dump_json()),
                )
                row = connection.execute(
                    "SELECT payload FROM sources WHERE id = ?", (source.id,)
                ).fetchone()
                sources.append(Source.model_validate_json(row[0]))
        return sources

    @staticmethod
    def _prepare(draft: SourceDraft) -> Source:
        # 完全相同的数据重复导入返回同一记录；修改内容会成为新版本。
        canonical = json.dumps(draft.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        source_id = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return Source(**draft.model_dump(), id=source_id, created_at=datetime.now(UTC).isoformat())

    def get(self, source_id: str) -> Source | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return Source.model_validate_json(row[0]) if row else None

    def list(
        self, author_id: str | None = None, *, offset: int = 0, limit: int | None = None
    ) -> list[Source]:
        where, params = self._filter(author_id)
        query = "SELECT payload FROM sources" + where + " ORDER BY id LIMIT ? OFFSET ?"
        with self._connection() as connection:
            rows = connection.execute(
                query, (*params, -1 if limit is None else limit, offset)
            ).fetchall()
        return [Source.model_validate_json(row[0]) for row in rows]

    @staticmethod
    def _filter(author_id: str | None, query: str = "") -> tuple[str, list[str]]:
        conditions = []
        params = []
        if author_id is not None:
            conditions.append("author_id = ?")
            params.append(author_id)
        if query:
            # instr treats %, _, quotes and backslashes literally; values never become SQL.
            fields = ("title", "author_name", "text")
            matches = [
                f"instr(lower(json_extract(payload, '$.{field}')), lower(?)) > 0"
                for field in fields
            ]
            matches.append(
                "EXISTS (SELECT 1 FROM json_each(sources.payload, '$.topics') "
                "WHERE instr(lower(value), lower(?)) > 0)"
            )
            conditions.append("(" + " OR ".join(matches) + ")")
            params.extend([query] * (len(fields) + 1))
        return (" WHERE " + " AND ".join(conditions) if conditions else ""), params

    def search(self, author_id: str | None, query: str, offset: int, limit: int) -> SourcePage:
        where, params = self._filter(author_id, query)
        with self._connection() as connection:
            # Explicit read transaction keeps count and items in one WAL snapshot.
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM sources" + where, params).fetchone()[0]
            rows = connection.execute(
                "SELECT payload FROM sources" + where + " ORDER BY id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        items = [Source.model_validate_json(row[0]) for row in rows]
        return SourcePage(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < total,
        )
