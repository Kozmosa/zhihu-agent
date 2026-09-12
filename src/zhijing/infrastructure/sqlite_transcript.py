import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path


class SQLiteTranscript:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self):
        # SQLite's transaction context commits/rolls back but does not close the handle.
        with closing(sqlite3.connect(self.path)) as connection, connection:
            yield connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS transcript_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, run_id TEXT, "
                "step_id TEXT, attempt INTEGER, event TEXT NOT NULL, provider TEXT, "
                "model TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcript_run ON transcript_events(run_id,id)"
            )

    def append(
        self,
        *,
        session_id="",
        run_id="",
        step_id="",
        attempt=0,
        event="model_call",
        provider="",
        model="",
        payload=None,
    ):
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO transcript_events "
                "(session_id,run_id,step_id,attempt,event,provider,model,payload,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    run_id,
                    step_id,
                    attempt,
                    event,
                    provider,
                    model,
                    json.dumps(payload or {}, ensure_ascii=False),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def list(self, run_id):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id,session_id,run_id,step_id,attempt,event,provider,model,payload,created_at "
                "FROM transcript_events WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        keys = [
            "id",
            "session_id",
            "run_id",
            "step_id",
            "attempt",
            "event",
            "provider",
            "model",
            "payload",
            "created_at",
        ]
        return [dict(zip(keys, row, strict=True)) | {"payload": json.loads(row[8])} for row in rows]
