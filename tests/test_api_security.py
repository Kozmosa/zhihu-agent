import re
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.local_auth import connect_local_client


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/sources"),
        ("GET", "/api/v1/knowledge-map"),
        ("GET", "/api/v1/runs"),
        ("GET", "/api/v1/settings/model"),
        ("GET", "/api/v1/zhihu/companion/inbox"),
        ("POST", "/api/v1/reading/analyze"),
        ("POST", "/api/v1/author/ask"),
        ("POST", "/api/v1/cards/generate"),
        ("POST", "/api/v1/facts/review"),
        ("POST", "/api/v1/companion/run"),
        ("POST", "/api/v1/runs/example/execute"),
        ("POST", "/api/v1/runs/example/retry"),
        ("POST", "/api/v1/runs/example/cancel"),
    ],
)
def test_api_requires_session_before_parsing_or_running_work(client, method, path):
    response = client.request(method, path, headers={"X-Zhijing-Token": ""}, content="invalid-json")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_config_token"
    assert response.headers["cache-control"] == "no-store"
    assert "invalid-json" not in response.text


@pytest.mark.parametrize("suffix", ["execute", "retry", "cancel"])
@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_site_bodyless_posts_never_enter_workflow(
    client, imported, monkeypatch, suffix, headers
):
    response = client.post(
        "/api/v1/runs",
        json={"source_id": imported[0]["id"], "tasks": ["reading"], "prepare_only": True},
        headers={"Idempotency-Key": "security-fixture"},
    )
    assert response.status_code == 200
    run = response.json()
    calls = Mock(side_effect=AssertionError("An unauthorized model workflow was invoked"))
    with client.app.state.runtime.lease() as container:
        monkeypatch.setattr(container.runs, suffix, calls)
    response = client.post(f"/api/v1/runs/{run['id']}/{suffix}", headers=headers)
    assert response.status_code == 403
    calls.assert_not_called()
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "pending"


def test_capture_credential_cannot_read_sources_or_spend_model_key(client):
    pair = client.post("/api/v1/zhihu/companion/pair", json={})
    assert pair.status_code == 200
    capture_token = pair.json()["token"]
    for method, path in [("GET", "/api/v1/sources"), ("POST", "/api/v1/author/ask")]:
        response = client.request(method, path, headers={"X-Zhijing-Token": capture_token})
        assert response.status_code == 403
    bad_capture = client.post(
        "/api/v1/zhihu/companion/receive",
        json={},
        headers={"X-Zhijing-Companion": client.app.state.config_token},
    )
    assert bad_capture.status_code == 403


@pytest.mark.parametrize("token", ["wrong-token", "令牌非ASCII", ""])
def test_invalid_session_never_echoes_or_causes_server_error(client, token):
    # Header bytes support arbitrary input; application comparisons must not raise TypeError.
    response = client.get("/api/v1/sources", headers={"X-Zhijing-Token": token.encode("utf-8")})
    assert response.status_code == 403
    assert client.app.state.config_token not in response.text


def test_local_cli_handshake_and_new_session_after_restart(tmp_path):
    options = {"base_url": "http://127.0.0.1", "client": ("127.0.0.1", 12345)}
    with TestClient(create_app(Settings(data_dir=tmp_path)), **options) as client:
        assert client.get("/api/v1/sources").status_code == 403
        connect_local_client(client)
        previous = client.headers["X-Zhijing-Token"]
        assert client.get("/api/v1/sources").status_code == 200
    with TestClient(create_app(Settings(data_dir=tmp_path)), **options) as client:
        assert (
            client.get("/api/v1/sources", headers={"X-Zhijing-Token": previous}).status_code == 403
        )
        connect_local_client(client)
        assert client.get("/api/v1/sources").status_code == 200


def test_csp_nonce_rotates_without_changing_api_session(client):
    first, second = client.get("/workspace"), client.get("/workspace")
    nonces = [
        re.search(r"nonce-([^']+)", page.headers["content-security-policy"])[1]
        for page in (first, second)
    ]
    assert nonces[0] != nonces[1]
    assert client.app.state.config_token not in nonces
    assert client.app.state.config_token != client.app.state.session_id
    for page, nonce in zip((first, second), nonces, strict=True):
        assert f'nonce="{nonce}"' in page.text
        assert f'data-session-id="{client.app.state.session_id}"' in page.text
        assert client.app.state.config_token not in page.headers["content-security-policy"]
    assert client.get("/api/v1/sources", headers={"X-Zhijing-Token": nonces[0]}).status_code == 403


def test_foreign_embedding_rejected_but_user_top_level_navigation_works(client):
    foreign = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}
    assert (
        client.get("/workspace", headers={**foreign, "Sec-Fetch-Dest": "iframe"}).status_code == 403
    )
    assert (
        client.get("/workspace", headers={**foreign, "Sec-Fetch-Dest": "document"}).status_code
        == 200
    )
    assert (
        client.get("/assets/workspace.js", headers={"Sec-Fetch-Site": "cross-site"}).status_code
        == 403
    )


def test_validation_errors_do_not_echo_request_secrets(client):
    secret = "synthetic-sensitive-input-do-not-echo"
    response = client.post("/api/v1/sources/import", json={"items": [{"text": secret}]})
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["error"]["code"] == "invalid_request"


def test_spoofed_host_does_not_pass_production_host_allowlist(client):
    for host in ["testserver", "localhost.foreign.example", "foreign.example"]:
        assert client.get("/workspace", headers={"Host": host}).status_code == 400


@pytest.mark.parametrize(
    "base",
    [
        "https://foreign.example",
        "http://localhost.foreign.example",
        "http://127.0.0.1/proxy",
        "http://user:password@127.0.0.1",
    ],
)
def test_cli_does_not_bootstrap_or_send_credentials_to_external_server(base):
    calls = []
    with httpx.Client(
        base_url=base, transport=httpx.MockTransport(lambda request: calls.append(request))
    ) as client:
        with pytest.raises(ValueError):
            connect_local_client(client)
    assert calls == []
