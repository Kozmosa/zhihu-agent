import sqlite3
from datetime import UTC, datetime

import pytest

from zhijing.infrastructure import sqlite_transcript
from zhijing.infrastructure.sqlite_transcript import SQLiteTranscript


@pytest.mark.parametrize("last_operation", ["initialize", "append", "list"])
def test_operations_release_database_without_garbage_collection(
    tmp_path, monkeypatch, last_operation
):
    path = tmp_path / "transcript.sqlite3"
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        # Keep strong references so garbage collection cannot hide a leaked handle.
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite_transcript.sqlite3, "connect", track_connection)
    transcript = SQLiteTranscript(path)
    transcript.initialize()
    if last_operation in {"append", "list"}:
        transcript.append(run_id="run-1", payload={"text": "fixture"})
    if last_operation == "list":
        assert len(transcript.list("run-1")) == 1

    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    path.unlink()
    assert not path.exists()


def test_records_keep_fields_payloads_order_and_run_filter(tmp_path):
    path = tmp_path / "transcript.sqlite3"
    transcript = SQLiteTranscript(path)
    transcript.initialize()
    metadata = {
        "session_id": "session-1",
        "run_id": "run-1",
        "step_id": "reading",
        "attempt": 2,
        "provider": "openai",
        "model": "fixture-model",
    }
    payload = {"text": "保留原文\n", "values": [1, 2]}
    transcript.append(**metadata, event="request", payload=payload)
    transcript.append(run_id="other-run")
    transcript.append(**metadata, event="response", payload={"response": "fixture"})

    records = SQLiteTranscript(path).list("run-1")
    for record in records:
        timestamp = datetime.fromisoformat(record.pop("created_at"))
        assert timestamp.tzinfo == UTC
    assert records == [
        {"id": 1, **metadata, "event": "request", "payload": payload},
        {"id": 3, **metadata, "event": "response", "payload": {"response": "fixture"}},
    ]
    other = transcript.list("other-run")[0]
    assert other["session_id"] == other["step_id"] == other["provider"] == other["model"] == ""
    assert other["attempt"] == 0
    assert other["event"] == "model_call"
    assert other["payload"] == {}
    assert transcript.list("missing-run") == []
