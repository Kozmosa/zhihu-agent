import hashlib
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import zhijing.container as container_module
from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.features.zhihu.service import plain_text

SECRET = "synthetic-zhihu-secret-do-not-echo"


def item(**changes):
    return {
        "Title": "学习<em>方法</em>",
        "ContentType": "Article",
        "ContentID": "123456789",
        "ContentText": "主动<em>回忆</em>有助于学习。",
        "Url": "https://zhuanlan.zhihu.com/p/123456789?utm_source=fixture&utm_medium=openapi_platform",
        "AuthorName": "测试作者",
        **changes,
    }


@pytest.fixture
def zhihu_api(monkeypatch, tmp_path):
    state = {
        "calls": [],
        "clients": [],
        "failure": None,
        "payload": {"Code": 0, "Data": {"Items": [item()]}},
    }
    original_client = httpx.Client

    def handle(request):
        state["calls"].append(request)
        if state["failure"] == "timeout":
            raise httpx.ReadTimeout(SECRET, request=request)
        if state["failure"] == "network":
            raise httpx.ConnectError(SECRET, request=request)
        if state["failure"] == "json":
            return httpx.Response(200, content=SECRET)
        if state["failure"] == "large":
            return httpx.Response(200, content=b"x" * 4_000_001)
        if isinstance(state["failure"], int):
            return httpx.Response(
                state["failure"], text=SECRET, headers={"Location": "https://third-party.invalid/"}
            )
        return httpx.Response(200, json=state["payload"])

    def build_client(**kwargs):
        client = original_client(**kwargs, transport=httpx.MockTransport(handle))
        state["clients"].append(client)
        return client

    monkeypatch.setattr(container_module, "httpx", SimpleNamespace(Client=build_client))
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        client=("127.0.0.1", 12345),
        base_url="http://127.0.0.1",
    ) as client:
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        yield client, state
    assert all(client.is_closed for client in state["clients"])


def configure(client, secret=SECRET):
    return client.post("/api/v1/zhihu/config", json={"access_secret": secret})


def search(client, **changes):
    return client.post("/api/v1/zhihu/search", json={"query": " 主动回忆 ", "count": 3, **changes})


def test_status_missing_secret_and_memory_configuration_are_quota_free(zhihu_api):
    client, state = zhihu_api
    status = client.get("/api/v1/zhihu/status")
    assert status.json() == {"configured": False}
    assert status.headers["cache-control"] == "no-store"
    response = search(client)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "zhihu_not_configured"
    assert configure(client).json() == {"configured": True}
    status = client.get("/api/v1/zhihu/status")
    assert status.json() == {"configured": True}
    assert SECRET not in status.text + repr(client.app.state.runtime.settings)
    assert configure(client, "").json() == {"configured": False}
    assert not state["calls"]


def test_official_request_produces_traceable_excerpt_without_import(zhihu_api, monkeypatch):
    client, state = zhihu_api
    monkeypatch.setattr("zhijing.infrastructure.zhihu_search.time.time", lambda: 1789201234.987)
    assert configure(client).status_code == 200
    response = search(client)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["has_more"] is False and result["skipped_count"] == 0
    draft = result["items"][0]
    assert draft["title"] == "学习方法"
    assert draft["text"] == "主动回忆有助于学习。"
    assert draft["origin"] == "zhihu" and draft["content_extent"] == "excerpt"
    assert draft["author_id"] == "zhihu-content:article:123456789"
    assert draft["provenance"]["external_author_id"] is None
    assert draft["url"] == item()["Url"]
    assert draft["provenance"]["canonical_url"] == "https://zhuanlan.zhihu.com/p/123456789"
    assert draft["provenance"]["content_hash"] == hashlib.sha256(draft["text"].encode()).hexdigest()
    assert (
        datetime.fromisoformat(draft["provenance"]["fetched_at"]).utcoffset().total_seconds() == 0
    )
    assert len(state["calls"]) == 1
    request = state["calls"][0]
    assert request.method == "GET" and str(request.url).startswith(Settings.zhihu_url + "?")
    assert dict(request.url.params) == {"Query": "主动回忆", "Count": "3"}
    assert request.headers["Authorization"] == "Bearer " + SECRET
    assert request.headers["X-Request-Timestamp"] == "1789201234"
    assert request.headers["Content-Type"] == "application/json"
    assert client.get("/api/v1/sources").json() == []
    assert SECRET not in response.text


@pytest.mark.parametrize("code,status", [(20001, 502), (30001, 429), (10001, 502), (90001, 502)])
def test_business_errors_are_not_success_and_do_not_echo_upstream(zhihu_api, code, status):
    client, state = zhihu_api
    configure(client)
    state["payload"] = {"Code": code, "Message": SECRET, "Data": {"Items": []}}
    response = search(client)
    assert response.status_code == status
    assert SECRET not in response.text
    assert len(state["calls"]) == 1


@pytest.mark.parametrize(
    "failure,status",
    [
        (401, 502),
        (403, 502),
        (429, 429),
        (500, 502),
        (302, 502),
        ("timeout", 504),
        ("network", 502),
        ("json", 502),
        ("large", 502),
    ],
)
def test_transport_failures_are_redacted_and_never_retried(zhihu_api, failure, status):
    client, state = zhihu_api
    configure(client)
    state["failure"] = failure
    response = search(client)
    assert response.status_code == status
    assert SECRET not in response.text and "third-party" not in response.text
    assert len(state["calls"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"Code": False, "Data": {"Items": []}},
        {"Code": "0"},
        {"Code": 0},
        {"Code": 0, "Data": {"Items": None}},
    ],
)
def test_malformed_success_shape_is_rejected(zhihu_api, payload):
    client, state = zhihu_api
    configure(client)
    state["payload"] = payload
    response = search(client)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "zhihu_invalid_response"


def test_empty_items_do_not_claim_content_or_return_upstream_empty_reason(zhihu_api):
    client, state = zhihu_api
    configure(client)
    state["payload"] = {"Code": 0, "Data": {"Items": [], "HasMore": True, "EmptyReason": SECRET}}
    response = search(client)
    assert response.status_code == 200
    result = response.json()
    assert result["items"] == [] and result["has_more"] is False
    assert "未返回搜索结果" in result["empty_reason"]
    assert SECRET not in response.text


def test_bad_items_are_skipped_without_losing_valid_summary(zhihu_api):
    client, state = zhihu_api
    configure(client)
    invalid = [
        item(ContentText=""),
        item(ContentText="x" * 100001),
        item(Title="x" * 201),
        item(Url="https://evil.example/p/1"),
        item(Url="https://zhihu.com.evil.example/p/1"),
        item(Url="http://www.zhihu.com/question/1"),
        item(Url="https://user:pass@www.zhihu.com/question/1"),
        item(ContentText=SECRET),
        None,
    ]
    state["payload"] = {"Code": 0, "Data": {"Items": [item(AuthorName=""), *invalid]}}
    response = search(client, count=10)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["items"]) == 1 and result["skipped_count"] == len(invalid)
    assert result["items"][0]["author_name"] == "未知作者"
    assert SECRET not in response.text


def test_html_highlights_and_scripts_are_removed_without_losing_comparisons():
    value = "<p>1 < 2 且 3 > 2；x<y and 3>2；<em>高亮</em></p><script>alert('bad')</script><style>body{}</style>尾部"
    cleaned = plain_text(value)
    assert "1 < 2 且 3 > 2" in cleaned
    assert "x<y and 3>2" in cleaned
    assert "高亮" in cleaned and "尾部" in cleaned
    assert "<em>" not in cleaned and "alert" not in cleaned and "body{}" not in cleaned
    assert plain_text("a<b and c>d") == "a<b and c>d"


@pytest.mark.parametrize(
    "value", [{"secret": SECRET}, SECRET + "\ninvalid", "非ASCII" + SECRET, SECRET * 500]
)
def test_invalid_secret_body_cannot_leak_validation_input(zhihu_api, value):
    client, state = zhihu_api
    response = configure(client, value)
    assert response.status_code in {413, 422}
    assert SECRET not in response.text
    assert not state["calls"]


@pytest.mark.parametrize(
    "changes",
    [
        {"query": "   "},
        {"query": "x" * 201},
        {"count": 0},
        {"count": 11},
        {"count": True},
        {"count": "3"},
    ],
)
def test_invalid_search_parameters_send_no_request(zhihu_api, changes):
    client, state = zhihu_api
    configure(client)
    assert search(client, **changes).status_code == 422
    assert not state["calls"]


@pytest.mark.parametrize(
    "route,method", [("status", "GET"), ("config", "POST"), ("search", "POST")]
)
def test_routes_reject_cross_origin_and_bad_session(zhihu_api, route, method):
    client, state = zhihu_api
    response = client.request(
        method,
        "/api/v1/zhihu/" + route,
        headers={"Origin": "https://evil.example"},
        json={"access_secret": SECRET} if route == "config" else {"query": "test"},
    )
    assert response.status_code == 403 and SECRET not in response.text
    if method == "POST":
        response = client.request(
            method,
            "/api/v1/zhihu/" + route,
            headers={"X-Zhijing-Token": "wrong"},
            json={"access_secret": SECRET} if route == "config" else {"query": "test"},
        )
        assert response.status_code == 403
    assert not state["calls"]


def test_all_routes_reject_nonlocal_client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path)), client=("192.0.2.1", 12345)) as client:
        client.headers["X-Zhijing-Token"] = client.app.state.config_token
        for method, route in [("GET", "status"), ("POST", "config"), ("POST", "search")]:
            response = client.request(method, "/api/v1/zhihu/" + route, json={})
            assert response.status_code == 403


def test_configuration_retains_active_client_until_lease_finishes(zhihu_api):
    client, state = zhihu_api
    runtime = client.app.state.runtime
    with runtime.lease() as initial:
        original_client = initial.zhihu_client
        assert configure(client).status_code == 200
        assert runtime.current.container is not initial
        assert not original_client.is_closed
    assert original_client.is_closed
    assert runtime.settings.model_provider == "extractive"
    assert not state["calls"]


def test_environment_secret_is_private_and_timeout_is_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ZHIHU_ACCESS_SECRET", SECRET)
    monkeypatch.setenv("ZHIHU_SEARCH_TIMEOUT", "25")
    settings = Settings.from_env()
    assert settings.zhihu_access_secret == SECRET and settings.zhihu_timeout == 25
    assert SECRET not in repr(settings)
    assert not settings.validation_errors()
    assert Settings(data_dir=tmp_path, zhihu_timeout=float("nan")).validation_errors()


def test_actual_search_drafts_deduplicate_across_tracking_urls_and_fetches(zhihu_api):
    client, state = zhihu_api
    configure(client)
    first = search(client).json()["items"][0]
    saved_first = client.post("/api/v1/sources/import", json={"items": [first]})
    assert saved_first.status_code == 200
    state["payload"] = {
        "Code": 0,
        "Data": {
            "Items": [
                item(
                    Url="https://zhuanlan.zhihu.com/p/123456789?utm_source=another-search#tracking"
                )
            ]
        },
    }
    second = search(client).json()["items"][0]
    assert first["url"] != second["url"]
    assert first["provenance"]["fetched_at"] != second["provenance"]["fetched_at"]
    assert first["provenance"]["canonical_url"] == second["provenance"]["canonical_url"]
    saved_second = client.post("/api/v1/sources/import", json={"items": [second]})
    assert saved_second.status_code == 200
    assert saved_first.json()[0]["id"] == saved_second.json()[0]["id"]
    assert len(client.get("/api/v1/sources").json()) == 1


def test_signed_opaque_content_id_is_preserved_independently_of_url_id(zhihu_api):
    client, state = zhihu_api
    configure(client)
    state["payload"] = {
        "Code": 0,
        "Data": {
            "Items": [
                item(
                    ContentID="-1234567890",
                    Url="https://zhuanlan.zhihu.com/p/987654321?utm_source=fixture",
                )
            ]
        },
    }
    response = search(client)
    assert response.status_code == 200
    result = response.json()
    assert result["skipped_count"] == 0 and len(result["items"]) == 1
    draft = result["items"][0]
    assert draft["provenance"]["external_id"] == "-1234567890"
    assert draft["author_id"] == "zhihu-content:article:-1234567890"
    assert draft["url"] == "https://zhuanlan.zhihu.com/p/987654321?utm_source=fixture"
    assert draft["provenance"]["canonical_url"] == "https://zhuanlan.zhihu.com/p/987654321"
    imported = client.post("/api/v1/sources/import", json={"items": [draft]})
    assert imported.status_code == 200
    assert imported.json()[0]["provenance"]["external_id"] == "-1234567890"
    assert client.get("/api/v1/sources").json()[0]["provenance"] == draft["provenance"]
