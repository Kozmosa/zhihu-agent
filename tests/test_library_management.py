import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.domain.models import SourceDraft
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository


def draft(question="123", answer="1", author="a", **changes):
    return SourceDraft(
        **{
            "title": "相同显示问题",
            "author_id": author,
            "author_name": "同名作者",
            "text": "作者的回答正文。",
            "origin": "zhihu",
            "url": f"https://www.zhihu.com/question/{question}/answer/{answer}",
            **changes,
        }
    )


@pytest.fixture
def repo(tmp_path):
    repository = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    repository.initialize()
    return repository


def test_groups_use_identity_not_display_names_and_filter_whole_library(repo):
    a, b, c = repo.save_many([draft(), draft(answer="2", author="b"), draft("456", "3")])
    authors = repo.groups("author", "同名", 0, 1)
    assert authors.total == 2 and authors.has_more
    assert authors.items[0].key == "a" and authors.items[0].count == 2
    questions = repo.groups("question", "", 0, 20)
    assert {g.key: g.count for g in questions.items} == {"123": 2, "456": 1}
    assert {s.id for s in repo.list(question_id="123")} == {a.id, b.id}
    assert repo.search("a", "正文", 0, 20, "123").items == [a]
    assert repo.search(None, "正文", 0, 20, "456").items == [c]


def test_missing_question_and_spoofed_links_are_not_merged_by_title(repo):
    repo.save_many([draft(url=None), draft(url="https://evil.example/question/123/answer/1")])
    group = repo.groups("question", "", 0, 20).items[0]
    assert (group.key, group.name, group.count) == ("", "未关联问题", 2)
    assert len(repo.list(question_id="")) == 2


def test_delete_is_idempotent_excludes_new_reads_and_explicit_reimport_restores(repo):
    a, b = repo.save_many([draft(), draft(answer="2")])
    assert repo.delete_many([a.id, a.id, "missing"]) == [a.id]
    assert repo.delete_many([a.id]) == []
    assert repo.get(a.id) is None and repo.list() == [b]
    assert repo.search(None, "", 0, 20).total == 1
    assert repo.groups("author", "", 0, 20).items[0].count == 1
    repo.initialize()
    assert repo.get(a.id) is None
    assert repo.save(draft()) == a
    assert repo.get(a.id) == a


def test_legacy_migration_preserves_payload_and_ids(tmp_path):
    path = tmp_path / "sources.sqlite3"
    source = SQLiteSourceRepository._prepare(draft())
    payload = source.model_dump_json()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sources (id TEXT PRIMARY KEY, author_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)", (source.id, source.author_id, payload)
        )
    repository = SQLiteSourceRepository(path)
    repository.initialize()
    repository.initialize()
    assert repository.list(question_id="123") == [source]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT payload FROM sources").fetchone()[0] == payload


def test_delete_rolls_back_entire_batch_on_storage_failure(repo):
    a, b = repo.save_many([draft(), draft(answer="2")])
    with sqlite3.connect(repo.path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_delete BEFORE UPDATE OF deleted ON sources WHEN NEW.id = '"
            + b.id
            + "' BEGIN SELECT RAISE(ABORT, 'fail'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_many([a.id, b.id])
    assert {s.id for s in repo.list()} == {a.id, b.id}


def test_migration_backfill_failure_rolls_back_schema_for_retry(tmp_path, monkeypatch):
    from zhijing.infrastructure import sqlite_sources

    path = tmp_path / "legacy.sqlite3"
    source = SQLiteSourceRepository._prepare(draft())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sources (id TEXT PRIMARY KEY, author_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)",
            (source.id, source.author_id, source.model_dump_json()),
        )
    original = sqlite_sources.source_question_id

    def fail(_source):
        raise RuntimeError("interrupted migration")

    monkeypatch.setattr(sqlite_sources, "source_question_id", fail)
    repository = SQLiteSourceRepository(path)
    with pytest.raises(RuntimeError):
        repository.initialize()
    with sqlite3.connect(path) as connection:
        assert [row[1] for row in connection.execute("PRAGMA table_info(sources)")] == [
            "id",
            "author_id",
            "payload",
        ]
    monkeypatch.setattr(sqlite_sources, "source_question_id", original)
    repository.initialize()
    assert repository.list(question_id="123") == [source]


def test_library_routes_delete_requires_local_session_and_validates_input(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 1234),
    ) as client:
        token = re.search(r'data-config-token="([^"]+)"', client.get("/workspace").text)[1]
        saved = client.post(
            "/api/v1/sources/import",
            headers={"X-Zhijing-Token": token},
            json={"items": [draft().model_dump(mode="json")]},
        ).json()[0]
        ids = {"source_ids": [saved["id"]]}
        assert client.post("/api/v1/sources/delete", json=ids).status_code == 403
        token = re.search(r'data-config-token="([^"]+)"', client.get("/workspace").text)[1]
        headers = {"X-Zhijing-Token": token}
        assert (
            client.post(
                "/api/v1/sources/delete",
                headers={**headers, "Origin": "https://evil.example"},
                json=ids,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/sources/delete", headers=headers, json={"source_ids": []}
            ).status_code
            == 422
        )
        client.headers.update(headers)
        groups = client.get("/api/v1/sources/groups?by=question").json()
        assert groups["items"][0]["key"] == "123"
        assert client.get("/api/v1/sources?question_id=123").json()[0]["id"] == saved["id"]
        result = client.post("/api/v1/sources/delete", headers=headers, json=ids)
        assert result.json() == {"deleted_ids": [saved["id"]], "deleted_count": 1}
        assert client.get("/api/v1/sources/" + saved["id"]).status_code == 404
        assert client.get("/api/v1/sources/groups?by=author").json()["total"] == 0
        assert client.get("/api/v1/sources/search").json()["items"] == []
