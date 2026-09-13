"""Authenticated browser text handoff with no external website requests."""

import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.features.zhihu.companion import CompanionInbox

PREFIX = "/api/v1/zhihu/companion"


def record(answer="100", **changes):
    return {
        "content_type": "answer",
        "external_id": answer,
        "question_id": "123",
        "title": "浏览器采集示例",
        "author_name": "同一测试昵称",
        "author_url": "https://www.zhihu.com/people/alice",
        "text": f"第 {answer} 篇回答\n\n- 列表\n- **加粗**\n\n| 标题 | 数值 |\n| --- | --- |\n| 项目 | 2 |",
        "content_extent": "unknown",
        "voteup_count": 200,
        "voteup_is_approximate": False,
        "url": f"https://www.zhihu.com/question/123/answer/{answer}",
        "captured_at": "2026-09-12T14:00:00Z",
        **changes,
    }


def payload(*items, **changes):
    return {
        "request_id": str(uuid4()),
        "page_url": "https://www.zhihu.com/question/123",
        "scope": "question",
        "scope_id": "123",
        "items": list(items) or [record()],
        **changes,
    }


@pytest.fixture
def companion(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12000),
    ) as client:
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        yield client, tmp_path


def connect(client):
    response = client.post(PREFIX + "/pair", json={})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return {"X-Zhijing-Companion": response.json()["token"], "Origin": "https://www.zhihu.com"}


def test_pairing_hash_survives_restart_without_plaintext_credential(companion):
    client, data = companion
    assert client.get(PREFIX + "/status").json() == {"paired": False, "pending_count": 0}
    headers = connect(client)
    token = headers["X-Zhijing-Companion"]
    stored = (data / "browser-companion-pairing.json").read_text("utf-8")
    assert token not in stored
    assert json.loads(stored)["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    restarted = CompanionInbox(data)
    restarted.authenticate(token)
    assert restarted.summaries() == []
    assert token not in client.get(PREFIX + "/status").text


def test_user_triggered_pair_and_local_inbox_keep_existing_origin_guards(companion):
    client, _ = companion
    assert (
        client.post(PREFIX + "/pair", json={}, headers={"X-Zhijing-Token": "bad"}).status_code
        == 403
    )
    assert (
        client.post(
            PREFIX + "/pair", json={}, headers={"Origin": "https://www.zhihu.com"}
        ).status_code
        == 403
    )
    assert (
        client.get(PREFIX + "/inbox", headers={"Origin": "https://www.zhihu.com"}).status_code
        == 403
    )
    assert client.post(PREFIX + "/receive", json=payload()).status_code == 403
    assert (
        client.post(
            PREFIX + "/receive", json=payload(), headers={"X-Zhijing-Companion": "x" * 43}
        ).status_code
        == 403
    )
    preflight = client.options(
        PREFIX + "/receive",
        headers={"Origin": "https://www.zhihu.com", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_capture_preview_then_explicit_import_preserves_markdown_and_author_scope(companion):
    client, _ = companion
    headers = connect(client)
    content = payload(
        record(), record("101"), record("102", author_url="https://www.zhihu.com/people/bob")
    )
    received = client.post(PREFIX + "/receive", json=content, headers=headers)
    assert received.status_code == 200
    assert received.json()["count"] == 3 and not received.json()["duplicate"]
    assert client.get("/api/v1/sources").json() == []
    batch = received.json()["batch_id"]
    listing = client.get(PREFIX + "/inbox").json()["items"]
    assert listing[0]["batch_id"] == batch and listing[0]["count"] == 3
    preview = client.get(PREFIX + "/inbox/" + batch).json()
    drafts = [item["draft"] for item in preview["items"]]
    assert drafts[0]["text"] == content["items"][0]["text"]
    assert all(item["content_extent"] == "unknown" for item in drafts)
    assert (
        drafts[0]["provenance"]["content_hash"]
        == hashlib.sha256(drafts[0]["text"].encode()).hexdigest()
    )
    saved = client.post("/api/v1/sources/import", json={"items": drafts}).json()
    replay = client.post("/api/v1/sources/import", json={"items": drafts}).json()
    assert [row["id"] for row in saved] == [row["id"] for row in replay]
    assert (
        len(client.get("/api/v1/sources", params={"author_id": "zhihu-author:people:alice"}).json()) == 2
    )
    assert len(client.get("/api/v1/sources", params={"author_id": "zhihu-author:people:bob"}).json()) == 1
    assert client.post(PREFIX + "/inbox/" + batch + "/dismiss", json={}).json() == {"removed": True}
    assert client.get(PREFIX + "/inbox/" + batch).status_code == 404
    assert len(client.get("/api/v1/sources").json()) == 3


def test_response_loss_replay_and_conflict(companion):
    client, _ = companion
    headers, content = connect(client), payload()
    first = client.post(PREFIX + "/receive", json=content, headers=headers).json()
    replay = client.post(PREFIX + "/receive", json=content, headers=headers).json()
    assert replay == {**first, "duplicate": True}
    assert client.get(PREFIX + "/status").json()["pending_count"] == 1
    content["items"][0]["text"] = "不同的正文"
    assert client.post(PREFIX + "/receive", json=content, headers=headers).status_code == 409


def test_anonymous_answers_are_not_grouped_by_display_name(companion):
    client, _ = companion
    response = client.post(
        PREFIX + "/receive",
        json=payload(record(author_url=None), record("101", author_url=None)),
        headers=connect(client),
    ).json()
    items = client.get(PREFIX + "/inbox/" + response["batch_id"]).json()["items"]
    assert len({item["draft"]["author_id"] for item in items}) == 2
    assert all(item["draft"]["provenance"]["external_author_id"] is None for item in items)


@pytest.mark.parametrize(
    "changes",
    [
        {"scope_id": "456"},
        {"page_url": "https://evil.example/question/123"},
        {"page_url": "https://user:password@www.zhihu.com/question/123"},
        {"page_url": "https://www.zhihu.com:443/question/123"},
        {"page_url": "http://127.0.0.1:8000/private"},
        {"items": [record(question_id="456")]},
        {"items": [record(url="https://www.zhihu.com/question/123/answer/999")]},
        {"items": [record(author_url="https://evil.example/people/alice")]},
        {"items": [record(author_url="https://www.zhihu.com/people/alice/answers")]},
        {
            "scope": "author",
            "scope_id": "alice",
            "page_url": "https://www.zhihu.com/people/alice/answers",
            "items": [record(author_url=None)],
        },
        {
            "scope": "author",
            "scope_id": "alice",
            "page_url": "https://www.zhihu.com/people/alice/answers",
            "items": [record(), record("101", author_url="https://www.zhihu.com/people/bob")],
        },
        {
            "scope": "page",
            "scope_id": None,
            "page_url": "https://www.zhihu.com/question/123/answer/999",
        },
    ],
)
def test_wrong_scope_or_unsafe_sources_rejected_atomically(companion, changes):
    client, _ = companion
    response = client.post(PREFIX + "/receive", json=payload(**changes), headers=connect(client))
    assert response.status_code == 422
    assert client.get(PREFIX + "/inbox").json() == {"items": []}


def test_partial_content_is_skipped_and_dom_never_asserts_full_text(companion):
    client, _ = companion
    response = client.post(
        PREFIX + "/receive",
        json=payload(record(content_extent="fulltext"), record("101", content_extent="excerpt")),
        headers=connect(client),
    ).json()
    preview = client.get(PREFIX + "/inbox/" + response["batch_id"]).json()
    assert len(preview["items"]) == 1 and preview["skipped_count"] == 1
    assert preview["items"][0]["draft"]["content_extent"] == "unknown"


def test_article_handoff_and_canonical_link(companion):
    client, _ = companion
    article = record(
        content_type="article",
        question_id=None,
        url="https://zhuanlan.zhihu.com/p/100?tracking=fixture",
    )
    capture = payload(
        article, scope="page", scope_id=None, page_url="https://zhuanlan.zhihu.com/p/100"
    )
    response = client.post(PREFIX + "/receive", json=capture, headers=connect(client)).json()
    draft = client.get(PREFIX + "/inbox/" + response["batch_id"]).json()["items"][0]["draft"]
    assert draft["url"] == "https://zhuanlan.zhihu.com/p/100"
    assert draft["provenance"]["content_type"] == "article"


def test_bad_payload_does_not_echo_input_and_queue_is_bounded(companion, monkeypatch):
    client, _ = companion
    headers = connect(client)
    bad = payload(record(text="synthetic-private-text", extra="synthetic-private-text"))
    response = client.post(PREFIX + "/receive", json=bad, headers=headers)
    assert response.status_code == 422 and "synthetic-private-text" not in response.text
    monkeypatch.setattr("zhijing.features.zhihu.companion.MAX_INBOX_BATCHES", 1)
    assert client.post(PREFIX + "/receive", json=payload(), headers=headers).status_code == 200
    assert (
        client.post(PREFIX + "/receive", json=payload(record("101")), headers=headers).status_code
        == 429
    )
    assert len(client.get(PREFIX + "/inbox").json()["items"]) == 1


def test_repair_revokes_previous_receiver_token(companion):
    client, _ = companion
    old = connect(client)
    current = connect(client)
    assert client.post(PREFIX + "/receive", json=payload(), headers=old).status_code == 403
    assert client.post(PREFIX + "/receive", json=payload(), headers=current).status_code == 200
