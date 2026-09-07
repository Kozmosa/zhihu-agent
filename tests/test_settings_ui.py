import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import zhijing.container as container_module
from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.runtime import Runtime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def setup_api(monkeypatch, tmp_path):
    state = {"calls": [], "failure": None}
    real_client = httpx.Client

    def handle(request):
        body = json.loads(request.content)
        state["calls"].append(request)
        if state["failure"] == "http":
            return httpx.Response(401, text="synthetic-secret-do-not-echo")
        if state["failure"] == "timeout":
            raise httpx.ReadTimeout("synthetic-secret-do-not-echo", request=request)
        prompt = json.loads(
            body["messages"][-1]["content"] if "messages" in body else body["prompt"]
        )
        if prompt["task"] == "connection_test":
            result = {"status": "ok"}
        else:
            from ollama_testing.fixtures import model_response

            result = model_response(prompt)
        content = json.dumps(result)
        if state["failure"] == "json":
            content = "not JSON synthetic-secret-do-not-echo"
        if "messages" in body:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": content},
                            "finish_reason": "length" if state["failure"] == "length" else "stop",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"response": content, "done": True})

    monkeypatch.setattr(
        container_module,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handle))
        ),
    )
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        client=("127.0.0.1", 12345),
        base_url="http://127.0.0.1",
    ) as client:
        page = client.get("/")
        token = re.search(r"const token='([^']+)'", page.text)[1]
        client.headers["X-Zhijing-Token"] = token
        yield client, state


def config(provider="openai"):
    return {
        "provider": provider,
        "base_url": "https://model.test/proxy/v1"
        if provider == "openai"
        else "http://model.test/proxy/api",
        "model": "fixture",
        "api_key": "synthetic-secret-do-not-echo",
        "output_format": "json",
    }


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_test_apply_offline_and_no_secret_disclosure(setup_api, provider):
    client, state = setup_api
    response = client.post("/api/v1/settings/model/test", json=config(provider))
    assert response.status_code == 200, response.text
    assert client.get("/health").json()["model_provider"] == "extractive"
    assert client.post("/api/v1/settings/model/apply", json=config(provider)).status_code == 200
    assert client.get("/health").json()["model_provider"] == provider
    status = client.get("/api/v1/settings/model")
    assert status.json()["has_api_key"] is True
    assert "synthetic-secret" not in status.text + response.text + client.get("/").text
    assert status.headers["cache-control"] == "no-store"
    assert state["calls"][0].headers["authorization"] == "Bearer synthetic-secret-do-not-echo"
    assert state["calls"][0].url.path == (
        "/proxy/v1/chat/completions" if provider == "openai" else "/proxy/api/generate"
    )
    assert (
        client.post("/api/v1/settings/model/apply", json={"provider": "extractive"}).status_code
        == 200
    )
    assert client.get("/health").json()["model_provider"] == "extractive"
    assert client.get("/api/v1/settings/model").json()["has_api_key"] is False


@pytest.mark.parametrize("failure", ["http", "timeout", "json", "length"])
def test_failed_apply_preserves_working_configuration(setup_api, failure):
    client, state = setup_api
    assert client.post("/api/v1/settings/model/apply", json=config()).status_code == 200
    original = client.app.state.runtime.current.container
    state["failure"] = failure
    response = client.post("/api/v1/settings/model/apply", json={**config(), "model": "broken"})
    assert response.status_code == 502
    assert "synthetic-secret" not in response.text
    assert client.app.state.runtime.current.container is original
    assert not original.model_client.is_closed
    assert client.get("/api/v1/settings/model").json()["model"] == "fixture"


@pytest.mark.parametrize(
    "updates",
    [
        {"api_key": {"secret": "synthetic-secret-do-not-echo"}},
        {"api_key": "synthetic-secret-do-not-echo\n"},
        {"base_url": "https://user:synthetic-secret-do-not-echo@model.test"},
        {"base_url": "https://model.test/v1/chat/completions"},
        {"output_format": "schema"},
        {"timeout": "bad"},
        {"context_window": 2048},
    ],
)
def test_invalid_configuration_is_redacted_and_never_contacts_upstream(setup_api, updates):
    client, state = setup_api
    response = client.post("/api/v1/settings/model/apply", json={**config(), **updates})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
    assert state["calls"] == []


def test_cross_origin_bad_host_and_token_rejected(setup_api):
    client, state = setup_api
    path = "/api/v1/settings/model/apply"
    assert (
        client.post(path, json=config(), headers={"Origin": "https://evil.test"}).status_code == 403
    )
    assert client.post(path, json=config(), headers={"X-Zhijing-Token": "bad"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.test"}).status_code == 400
    assert (
        client.get("/api/v1/settings/model", headers={"Origin": "https://evil.test"}).status_code
        == 403
    )
    assert state["calls"] == []


def test_remote_configuration_rejected(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path)), client=("192.0.2.3", 12345)) as client:
        assert client.get("/").status_code == 403
        assert client.get("/api/v1/settings/model").status_code == 403


def test_reconfiguration_waits_for_inflight_client_before_close(tmp_path):
    runtime = Runtime(Settings(data_dir=tmp_path))
    old = runtime.current.container
    closed = []
    old.close = lambda: closed.append(True)
    new = container_module.build_container(Settings(data_dir=tmp_path))
    with runtime.lease() as leased:
        runtime.activate(Settings(data_dir=tmp_path), new)
        assert leased is old
        assert closed == []
        with runtime.lease() as current:
            assert current is new
    assert closed == [True]
    runtime.close()


def test_slow_configuration_cannot_overwrite_newer_activation(tmp_path):
    runtime = Runtime(Settings(data_dir=tmp_path))
    candidate = container_module.build_container(Settings(data_dir=tmp_path))
    runtime.activate(runtime.settings, candidate, expected_revision=0)
    stale = container_module.build_container(Settings(data_dir=tmp_path))
    with pytest.raises(DomainError, match="另一操作"):
        runtime.activate(runtime.settings, stale, expected_revision=0)
    assert runtime.current.container is candidate
    stale.close()
    runtime.close()


def test_prompt_format_omits_response_format_and_empty_key_clears_auth(setup_api):
    client, state = setup_api
    assert client.post("/api/v1/settings/model/apply", json=config()).status_code == 200
    response = client.post(
        "/api/v1/settings/model/apply", json={**config(), "output_format": "prompt", "api_key": ""}
    )
    assert response.status_code == 200
    assert "response_format" not in json.loads(state["calls"][-1].content)
    assert "authorization" not in state["calls"][-1].headers
    assert client.get("/api/v1/settings/model").json()["has_api_key"] is False


@pytest.mark.parametrize("task", ["reading", "cards", "facts", "knowledge", "author"])
def test_compatible_api_runs_all_five_capabilities(setup_api, task):
    from ollama_testing.fixtures import IMPORT_BODY, api_requests

    client, state = setup_api
    imported = client.post("/api/v1/sources/import", json=IMPORT_BODY)
    source_id = imported.json()[0]["id"]
    assert client.post("/api/v1/settings/model/apply", json=config()).status_code == 200
    _, method, path, payload = next(item for item in api_requests(source_id) if item[0] == task)
    response = client.request(method, path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "openai"
    assert len(state["calls"]) == 2
    body = json.loads(state["calls"][-1].content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False
