import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

from pydantic import HttpUrl

from zhijing.domain.models import SourceDraft, SourceProvenance
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository


def search_draft(text="搜索返回的摘要", **changes):
    provenance = SourceProvenance(
        external_id="123",
        content_type="answer",
        canonical_url="https://www.zhihu.com/question/1/answer/123",
        fetched_at=datetime(2026, 9, 12, tzinfo=UTC),
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    return SourceDraft(
        **{
            "title": "如何有效学习？",
            "author_name": "同名作者",
            "author_id": "zhihu-content:answer:123",
            "text": text,
            "url": "https://www.zhihu.com/question/1/answer/123?utm_source=first",
            "origin": "zhihu",
            "content_extent": "excerpt",
            "provenance": provenance,
            **changes,
        }
    )


def test_repeated_search_import_keeps_original_record_and_provenance(tmp_path):
    repository = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    repository.initialize()
    draft = search_draft()
    stored = repository.save(draft)
    repeated = draft.model_copy(
        update={
            "url": HttpUrl("https://www.zhihu.com/question/1/answer/123?utm_source=second"),
            "provenance": draft.provenance.model_copy(
                update={"fetched_at": draft.provenance.fetched_at + timedelta(days=1)}
            ),
        }
    )
    assert repository.save(repeated) == stored
    assert len(repository.list()) == 1
    reloaded = repository.get(stored.id)
    assert reloaded.content_extent == "excerpt"
    assert reloaded.provenance.external_author_id is None
    assert reloaded.provenance == draft.provenance


def test_changed_summary_is_a_new_content_version(tmp_path):
    repository = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    repository.initialize()
    first = repository.save(search_draft())
    updated = repository.save(search_draft("另一份更新后的摘要"))
    assert first.id != updated.id
    assert len(repository.list()) == 2


def test_import_api_retains_excerpt_metadata(client):
    draft = search_draft()
    response = client.post(
        "/api/v1/sources/import", json={"items": [draft.model_dump(mode="json")]}
    )
    assert response.status_code == 200
    source = response.json()[0]
    assert source["content_extent"] == "excerpt"
    assert source["provenance"]["content_hash"] == hashlib.sha256(draft.text.encode()).hexdigest()
    assert client.get("/api/v1/sources/" + source["id"]).json() == source


def test_legacy_payload_loads_without_fulltext_claim_or_duplicate_on_reimport(tmp_path):
    # A pre-provenance payload and ID, using the original public import contract.
    legacy = {
        "title": "历史资料",
        "author_id": "author-a",
        "author_name": "作者",
        "text": "此前导入的内容，完整性未知。",
        "url": None,
        "topics": [],
        "origin": "manual",
    }
    legacy_id = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:24]
    payload = {**legacy, "id": legacy_id, "created_at": "2026-09-01T00:00:00Z"}
    repository = SQLiteSourceRepository(tmp_path / "sources.sqlite3")
    repository.initialize()
    with closing(sqlite3.connect(repository.path)) as connection, connection:
        connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?)",
            (legacy_id, legacy["author_id"], json.dumps(payload, ensure_ascii=False)),
        )
    stored = repository.get(legacy_id)
    assert stored.content_extent == "unknown"
    assert stored.provenance is None
    assert repository.save(SourceDraft(**legacy)) == stored
    assert len(repository.list()) == 1
