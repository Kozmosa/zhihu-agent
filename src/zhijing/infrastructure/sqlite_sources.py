"""一个操作一个连接；同一批导入由服务控制，单条写入原子提交。"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from zhijing.domain.models import Source, SourceDraft


class SQLiteSourceRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
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
        # 完全相同的数据重复导入返回同一记录；修改内容会成为新版本。
        canonical = json.dumps(draft.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        source_id = hashlib.sha256(canonical.encode()).hexdigest()[:24]
        source = Source(
            **draft.model_dump(), id=source_id, created_at=datetime.now(UTC).isoformat()
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO sources VALUES (?, ?, ?)",
                (source.id, source.author_id, source.model_dump_json()),
            )
            row = connection.execute(
                "SELECT payload FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return Source.model_validate_json(row[0])

    def get(self, source_id: str) -> Source | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        return Source.model_validate_json(row[0]) if row else None

    def list(self, author_id: str | None = None) -> list[Source]:
        query = "SELECT payload FROM sources"
        params = ()
        if author_id is not None:
            query += " WHERE author_id = ?"
            params = (author_id,)
        query += " ORDER BY id"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [Source.model_validate_json(row[0]) for row in rows]
