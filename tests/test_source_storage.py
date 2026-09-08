import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from zhijing.domain.models import Source, SourceDraft
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository


def draft(title="事务资料", **changes):
    return SourceDraft(
        **{
            "title": title,
            "author_id": "author-a",
            "author_name": "测试作者",
            "text": "保留原文与证据。",
            **changes,
        }
    )


@pytest.fixture
def repository(tmp_path):
    result = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    result.initialize()
    return result


def test_batch_storage_failure_rolls_back_new_rows_and_preserves_existing(repository):
    existing = repository.save(draft("已有资料"))
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_test BEFORE INSERT ON sources "
            "WHEN NEW.author_id = 'reject' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_many(
            [draft("已有资料"), draft("本应回滚"), draft("故障资料", author_id="reject")]
        )
    assert repository.list() == [existing]
    # The failed connection released its write lock.
    assert repository.save(draft("之后可写")).title == "之后可写"


def test_batch_duplicates_keep_order_timestamp_and_original_text(repository):
    first = draft(text="  开头\r\n\n原文末尾  ")
    second = draft("第二篇")
    result = repository.save_many([first, second, first])
    assert result[0] == result[2]
    assert result[0].text == first.text
    assert repository.save_many([first, second]) == result[:2]
    assert len(repository.list()) == 2


def test_concurrent_duplicate_batches_are_idempotent(repository):
    drafts = [draft("第一篇"), draft("第二篇")]
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: repository.save_many(drafts), range(8)))
    assert all(result == results[0] for result in results)
    assert len(repository.list()) == 2


def test_list_only_deserializes_requested_page(repository, monkeypatch):
    repository.save_many([draft(str(i)) for i in range(30)])
    all_rows = repository.list()
    original = Source.model_validate_json
    decoded = []

    def record(payload):
        decoded.append(payload)
        return original(payload)

    monkeypatch.setattr(Source, "model_validate_json", record)
    assert repository.list(offset=13, limit=2) == all_rows[13:15]
    assert len(decoded) == 2


def test_search_count_and_page_share_snapshot(repository, monkeypatch):
    original_source = repository.save(draft("已存在"))
    writer = SQLiteSourceRepository(repository.path)
    original_connection = repository._connection
    writes = []

    @contextmanager
    def concurrent_connection():
        with original_connection() as connection:

            def trace(sql):
                if sql.startswith("SELECT payload") and not writes:
                    writes.append(writer.save(draft("并发新增")))

            connection.set_trace_callback(trace)
            yield connection

    monkeypatch.setattr(repository, "_connection", concurrent_connection)
    page = repository.search(None, "", 0, 20)
    assert len(writes) == 1
    assert page.total == 1
    assert page.items == [original_source]
    assert not page.has_more
    assert len(writer.list()) == 2


def test_existing_v1_database_works_without_reimport(tmp_path):
    path = tmp_path / "old.sqlite3"
    source = Source(**draft().model_dump(), id="legacy-source", created_at="2026-09-01T00:00:00Z")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sources (id TEXT PRIMARY KEY, author_id TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version=1")
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)",
            (source.id, source.author_id, source.model_dump_json()),
        )
    repository = SQLiteSourceRepository(path)
    repository.initialize()
    assert repository.search(None, "事务", 0, 20).items == [source]
    assert repository.get(source.id) == source


def test_storage_busy_returns_retryable_error_without_partial_import(client, monkeypatch):
    repository = client.app.state.runtime.current.container.sources.repository
    real_connect = sqlite3.connect

    def immediate_connect(path, **kwargs):
        return real_connect(path, **{**kwargs, "timeout": 0})

    monkeypatch.setattr(sqlite3, "connect", immediate_connect)
    with real_connect(repository.path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        response = client.post(
            "/api/v1/sources/import", json={"items": [draft().model_dump(mode="json")]}
        )
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "storage_busy", "message": "资料库暂时繁忙，请稍后重试。"}
    }
    assert repository.list() == []


@pytest.mark.parametrize(
    "field,value,query",
    [
        ("title", "深度阅读", "阅读"),
        ("author_name", "特别作者", "特别"),
        ("text", "正文里的唯一证据", "唯一证据"),
        ("topics", ["知识图谱", "知识图谱"], "图谱"),
        ("title", "SQLite Backend", "sqlite backend"),
        ("text", "100% 确定", "%"),
        ("title", "under_score", "_"),
        ("text", "路径 a\\b", "\\"),
        ("text", "原文包含 ' OR 1=1 --", "' OR 1=1 --"),
    ],
)
def test_search_matches_literal_fields(client, field, value, query):
    matching = draft(**{field: value})
    unrelated = draft("不匹配", author_id="author-b", author_name="其他", text="无关正文")
    imported = client.post(
        "/api/v1/sources/import",
        json={"items": [item.model_dump(mode="json") for item in [matching, unrelated]]},
    ).json()
    response = client.get("/api/v1/sources/search", params={"q": "  " + query + "  "})
    assert response.status_code == 200
    page = response.json()
    assert page["items"] == [imported[0]]
    assert page["total"] == 1
    assert not page["has_more"]


def test_search_pagination_author_filter_and_empty_results(client, imported):
    rows = client.get("/api/v1/sources", params={"author_id": "demo-author-1"}).json()
    first = client.get(
        "/api/v1/sources/search", params={"author_id": "demo-author-1", "limit": 1}
    ).json()
    assert first == {"items": rows[:1], "total": 2, "offset": 0, "limit": 1, "has_more": True}
    second = client.get(
        "/api/v1/sources/search", params={"author_id": "demo-author-1", "limit": 1, "offset": 1}
    ).json()
    assert second == {"items": rows[1:], "total": 2, "offset": 1, "limit": 1, "has_more": False}
    beyond = client.get("/api/v1/sources/search", params={"offset": 100}).json()
    assert beyond["total"] == 3
    assert beyond["items"] == []
    assert not beyond["has_more"]
    blank = client.get("/api/v1/sources/search", params={"q": "   "}).json()
    assert blank["total"] == 3
    for params in [
        {"q": "找不到的短语"},
        {"author_id": "unknown"},
        {"q": rows[0]["title"], "author_id": "unknown"},
    ]:
        empty = client.get("/api/v1/sources/search", params=params).json()
        assert empty["total"] == 0
        assert empty["items"] == []
        assert not empty["has_more"]


@pytest.mark.parametrize(
    "params", [{"offset": -1}, {"limit": 0}, {"limit": 101}, {"q": "字" * 201}]
)
def test_search_rejects_invalid_pagination_and_query(client, params):
    assert client.get("/api/v1/sources/search", params=params).status_code == 422


def test_search_empty_library(client):
    assert client.get("/api/v1/sources/search").json() == {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 20,
        "has_more": False,
    }


@pytest.mark.parametrize("endpoint", ["/api/v1/sources", "/api/v1/sources/search"])
def test_sqlite_offset_overflow_is_validation_error(client, endpoint):
    assert client.get(endpoint, params={"offset": 2**63}).status_code == 422
