"""批量导入使用单个事务；分页与搜索在数据库内执行。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source, SourceDraft, SourceGroup, SourceGroupPage, SourcePage
from zhijing.domain.source_identity import source_question_id


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
            # Serialize schema upgrades and roll back both columns and backfill on failure.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sources "
                "(id TEXT PRIMARY KEY, author_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_author ON sources(author_id)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(sources)")}
            if "question_id" not in columns:
                connection.execute("ALTER TABLE sources ADD COLUMN question_id TEXT")
                for source_id, payload in connection.execute(
                    "SELECT id, payload FROM sources"
                ).fetchall():
                    connection.execute(
                        "UPDATE sources SET question_id = ? WHERE id = ?",
                        (source_question_id(Source.model_validate_json(payload)), source_id),
                    )
            if "deleted" not in columns:
                connection.execute(
                    "ALTER TABLE sources ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_question ON sources(question_id)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS question_titles "
                "(question_id TEXT PRIMARY KEY, title TEXT NOT NULL)"
            )
            connection.execute("PRAGMA user_version=2")

    def save(self, draft: SourceDraft) -> Source:
        return self.save_many([draft])[0]

    def save_many(self, drafts: list[SourceDraft]) -> list[Source]:
        sources = []
        with self._connection() as connection:
            for draft in drafts:
                source = self._prepare(draft)
                connection.execute(
                    "INSERT INTO sources (id, author_id, payload, question_id) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET deleted = 0",
                    (
                        source.id,
                        source.author_id,
                        source.model_dump_json(),
                        source_question_id(source),
                    ),
                )
                row = connection.execute(
                    "SELECT payload FROM sources WHERE id = ?", (source.id,)
                ).fetchone()
                sources.append(Source.model_validate_json(row[0]))
        return sources

    @staticmethod
    def _prepare(draft: SourceDraft) -> Source:
        # 完全相同的数据重复导入返回同一记录；修改内容会成为新版本。
        identity = draft.model_dump(mode="json", exclude={"content_extent", "provenance"})
        # Preserve IDs from the original schema for legacy/manual imports.
        if draft.content_extent != "unknown":
            identity["content_extent"] = draft.content_extent
        if draft.provenance:
            # The same result can be fetched again with a new timestamp or tracking URL.
            # Neither changes the content version; retain the first stored provenance.
            identity["provenance"] = draft.provenance.model_dump(
                mode="json", exclude={"fetched_at"}
            )
            identity["url"] = str(draft.provenance.canonical_url)
        canonical = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        source_id = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        return Source(**draft.model_dump(), id=source_id, created_at=datetime.now(UTC).isoformat())

    def get(self, source_id: str) -> Source | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM sources WHERE id = ? AND deleted = 0", (source_id,)
            ).fetchone()
        return Source.model_validate_json(row[0]) if row else None

    def list(
        self,
        author_id: str | None = None,
        *,
        offset: int = 0,
        limit: int | None = None,
        question_id: str | None = None,
    ) -> list[Source]:
        where, params = self._filter(author_id, question_id=question_id)
        query = "SELECT payload FROM sources" + where + " ORDER BY id LIMIT ? OFFSET ?"
        with self._connection() as connection:
            rows = connection.execute(
                query, (*params, -1 if limit is None else limit, offset)
            ).fetchall()
        return [Source.model_validate_json(row[0]) for row in rows]

    @staticmethod
    def _filter(
        author_id: str | None, query: str = "", question_id: str | None = None
    ) -> tuple[str, list[str]]:
        conditions = ["deleted = 0"]
        params = []
        if author_id is not None:
            conditions.append("author_id = ?")
            params.append(author_id)
        if question_id is not None:
            conditions.append("COALESCE(question_id, '') = ?")
            params.append(question_id)
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

    def search(
        self,
        author_id: str | None,
        query: str,
        offset: int,
        limit: int,
        question_id: str | None = None,
    ) -> SourcePage:
        where, params = self._filter(author_id, query, question_id)
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

    def groups(self, by: str, query: str, offset: int, limit: int) -> SourceGroupPage:
        if by not in {"author", "question"}:
            raise ValueError("Unknown grouping")
        key = "author_id" if by == "author" else "COALESCE(question_id, '')"
        name = (
            "MIN(json_extract(payload, '$.author_name'))"
            if by == "author"
            else (
                "CASE WHEN question_id IS NULL THEN '未关联问题' ELSE COALESCE("
                "(SELECT title FROM question_titles WHERE question_titles.question_id = sources.question_id), "
                "MIN(CASE WHEN trim(json_extract(payload, '$.title')) != trim(json_extract(payload, '$.author_name')) "
                "AND trim(json_extract(payload, '$.title')) NOT IN ('未提供题目', '(未能解析出标题/问题文本)') "
                "THEN json_extract(payload, '$.title') END), "
                "'问题 ' || question_id || '（标题待补全）') END"
            )
        )
        grouped = f"SELECT {key} AS key, {name} AS name, COUNT(*) AS count FROM sources WHERE deleted = 0 GROUP BY {key}"
        filtered = f"SELECT * FROM ({grouped}) WHERE instr(lower(name), lower(?)) > 0 OR instr(lower(key), lower(?)) > 0"
        with self._connection() as connection:
            connection.execute("BEGIN")
            total = connection.execute(
                f"SELECT COUNT(*) FROM ({filtered})", (query, query)
            ).fetchone()[0]
            rows = connection.execute(
                filtered + " ORDER BY name, key LIMIT ? OFFSET ?", (query, query, limit, offset)
            ).fetchall()
        return SourceGroupPage(
            items=[SourceGroup(key=r[0], name=r[1], count=r[2]) for r in rows],
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(rows) < total,
        )

    def set_question_title(self, question_id: str, title: str) -> SourceGroup:
        # Question metadata does not rewrite source evidence or stable IDs.
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute(
                "SELECT COUNT(*) FROM sources WHERE question_id = ? AND deleted = 0", (question_id,)
            ).fetchone()[0]
            if not count:
                raise DomainError("question_not_found", "资料库中没有这个问题的回答。", 404)
            connection.execute(
                "INSERT INTO question_titles VALUES (?, ?) "
                "ON CONFLICT(question_id) DO UPDATE SET title = excluded.title", (question_id, title)
            )
        return SourceGroup(key=question_id, name=title, count=count)

    def delete_many(self, source_ids: list[str]) -> list[str]:
        # Tombstones exclude sources from all new reads/retrieval; existing run artifacts stay intact.
        source_ids = list(dict.fromkeys(source_ids))
        placeholders = ",".join("?" for _ in source_ids)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"SELECT id FROM sources WHERE deleted = 0 AND id IN ({placeholders})", source_ids
            ).fetchall()
            connection.execute(
                f"UPDATE sources SET deleted = 1 WHERE id IN ({placeholders})", source_ids
            )
        return [row[0] for row in rows]
