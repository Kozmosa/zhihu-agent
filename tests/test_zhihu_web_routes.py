"""Route boundaries and library handoff, with no external requests."""

import hashlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.domain.models import SourceDraft, SourceProvenance
from zhijing.features.zhihu import web_router
from zhijing.features.zhihu.web_schemas import ZhihuWebItem, ZhihuWebPreviewResult

COOKIE = "session=synthetic-local-login-do-not-echo"
PREFIX = "/api/v1/zhihu/web"


def draft(answer_id="100", text="第一篇完整测试回答，包含可供后续问答引用的原文。"):
    url = f"https://www.zhihu.com/question/123/answer/{answer_id}"
    return SourceDraft(
        title="批量导入测试问题",
        author_id="zhihu-author:fixture-account",
        author_name="测试作者",
        text=text,
        url=url,
        origin="zhihu",
        content_extent="fulltext",
        topics=["知乎问题:123"],
        provenance=SourceProvenance(
            external_id=answer_id,
            content_type="answer",
            canonical_url=url,
            fetched_at=datetime.now(UTC),
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            external_author_id="fixture-account",
        ),
    )


@pytest.fixture
def web_api(tmp_path, monkeypatch):
    calls = []

    class StubService:
        def preview(self, body, cookie=""):
            calls.append((body, cookie))
            return ZhihuWebPreviewResult(
                items=[
                    ZhihuWebItem(
                        draft=draft(), answer_id="100", question_id="123", voteup_count=800
                    ),
                    ZhihuWebItem(
                        draft=draft("101", "第二篇完整测试回答，与第一篇属于同一个知乎账号。"),
                        answer_id="101",
                        question_id="123",
                        voteup_count=500,
                    ),
                ],
                scanned_count=2,
                skipped_count=0,
                pages_fetched=1,
                has_more=False,
                stop_reason="completed",
                warning="",
                target_label="测试问题",
            )

    monkeypatch.setattr(web_router, "ZhihuWebService", StubService)
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        yield client, calls


def test_preview_is_explicit_and_batch_import_groups_author_idempotently(web_api):
    client, calls = web_api
    assert client.get(PREFIX + "/status").json() == {"configured": False}
    result = client.post(
        PREFIX + "/preview",
        json={
            "mode": "question",
            "url": "https://www.zhihu.com/question/123",
            "min_votes": 100,
            "max_items": 20,
        },
    )
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert len(calls) == 1 and calls[0][1] == ""
    assert client.get("/api/v1/sources").json() == []
    batch = {"items": [item["draft"] for item in result.json()["items"]]}
    saved = client.post("/api/v1/sources/import", json=batch)
    assert saved.status_code == 200
    replay = client.post("/api/v1/sources/import", json=batch)
    assert [item["id"] for item in replay.json()] == [item["id"] for item in saved.json()]
    library = client.get(
        "/api/v1/sources", params={"author_id": "zhihu-author:fixture-account"}
    ).json()
    assert len(library) == 2
    assert all(item["provenance"]["external_author_id"] == "fixture-account" for item in library)


def test_login_stays_in_session_and_configuration_does_not_fetch(web_api):
    client, calls = web_api
    configured = client.post(PREFIX + "/config", json={"cookie": COOKIE})
    assert configured.json() == {"configured": True}
    assert configured.headers["cache-control"] == "no-store"
    assert not calls and COOKIE not in configured.text
    runtime = client.app.state.runtime
    assert COOKIE not in repr(runtime.settings)
    # Changing the official API configuration must leave website login intact.
    assert (
        client.post("/api/v1/zhihu/config", json={"access_secret": "fixture-official"}).status_code
        == 200
    )
    assert client.get(PREFIX + "/status").json() == {"configured": True}
    result = client.post(
        PREFIX + "/preview",
        json={"mode": "author", "url": "https://www.zhihu.com/people/fixture-account"},
    )
    assert result.status_code == 200 and calls[-1][1] == COOKIE
    assert COOKIE not in result.text
    assert client.post(PREFIX + "/config", json={"cookie": ""}).json() == {"configured": False}
    assert runtime.zhihu_web_cookie == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"cookie": COOKIE + "\r\nX-Injected: bad"},
        {"cookie": COOKIE, "unexpected": COOKIE},
        {"cookie": {"value": COOKIE}},
        {"cookie": COOKIE + "x" * 20000},
    ],
)
def test_invalid_login_never_echoes_input(web_api, payload):
    client, calls = web_api
    response = client.post(PREFIX + "/config", json=payload)
    assert response.status_code in {413, 422}
    assert COOKIE not in response.text and not calls
    assert client.get(PREFIX + "/status").json() == {"configured": False}


def test_foreign_origin_missing_token_and_overlapping_requests_are_rejected(web_api):
    client, calls = web_api
    body = {"mode": "question", "url": "https://www.zhihu.com/question/123"}
    assert (
        client.post(
            PREFIX + "/preview", json=body, headers={"Origin": "https://www.zhihu.com"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            PREFIX + "/config", json={"cookie": COOKIE}, headers={"X-Zhijing-Token": "wrong"}
        ).status_code
        == 403
    )
    runtime = client.app.state.runtime
    with runtime.zhihu_web_lock:
        blocked = client.post(PREFIX + "/preview", json=body)
        assert blocked.status_code == 409
    assert not calls
    assert client.post(PREFIX + "/preview", json=body).status_code == 200
    assert not runtime.zhihu_web_lock.locked()


def test_preview_failure_releases_session_slot(web_api, monkeypatch):
    client, _ = web_api

    class Broken:
        def preview(self, body, cookie=""):
            from zhijing.core.errors import DomainError

            raise DomainError("test_failure", "读取失败", 502)

    monkeypatch.setattr(web_router, "ZhihuWebService", Broken)
    response = client.post(
        PREFIX + "/preview", json={"mode": "question", "url": "https://www.zhihu.com/question/123"}
    )
    assert response.status_code == 502
    assert not client.app.state.runtime.zhihu_web_lock.locked()


def test_shutdown_clears_login(web_api):
    client, _ = web_api
    client.post(PREFIX + "/config", json={"cookie": COOKIE})
    client.app.state.runtime.close()
    assert client.app.state.runtime.zhihu_web_cookie == ""
