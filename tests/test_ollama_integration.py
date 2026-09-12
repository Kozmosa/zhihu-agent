"""Public API contracts with the real Ollama adapter and a mocked HTTP transport."""

import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import zhijing.container as container_module
from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.local_auth import connect_local_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ollama_smoke  # noqa: E402
from ollama_testing.fixtures import (  # noqa: E402
    CLAIM,
    IMPORT_BODY,
    SOURCE_TEXT,
    api_requests,
    model_response,
)

TASKS = ["reading", "cards", "facts", "knowledge", "author"]


@pytest.fixture
def ollama_api(monkeypatch, tmp_path):
    state = {"calls": [], "failure": None}
    real_client = httpx.Client

    def handle(request):
        assert request.method == "POST"
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        prompt = json.loads(body["prompt"])
        assert body["model"] == "contract-fixture"
        assert body["stream"] is False
        assert body["format"] == prompt["schema"]
        assert prompt["schema"]["type"] == "object"
        state["calls"].append(prompt)
        if state["failure"] == "http":
            return httpx.Response(503, text="upstream unavailable")
        if state["failure"] == "invalid_json":
            return httpx.Response(200, json={"response": "This is not JSON."})
        result = model_response(prompt)
        if state["failure"] == "invalid_reference":
            corrupt_reference(prompt["task"], result)
        return httpx.Response(200, json={"response": json.dumps(result), "done": True})

    def model_client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(container_module, "httpx", SimpleNamespace(Client=model_client))
    settings = Settings(
        data_dir=tmp_path,
        model_provider="ollama",
        ollama_url="https://model-fixture",
        ollama_model="contract-fixture",
    )
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", client=("127.0.0.1", 12345)
    ) as client:
        connect_local_client(client)
        imported = client.post("/api/v1/sources/import", json=IMPORT_BODY)
        assert imported.status_code == 200
        source_id = imported.json()[0]["id"]
        yield client, state, source_id


def corrupt_reference(task, result):
    if task == "reading":
        result["sections"][0]["index"] = 999
    elif task == "cards":
        result["cards"][0]["evidence_excerpt"] = "This quotation never occurred in the source."
    elif task == "facts":
        result["assessments"][0]["evidence_id"] = "nonexistent-evidence"
    elif task == "knowledge":
        result["edges"][0]["target"] = "nonexistent-concept"
    else:
        result["answer"] = "An invented reference [999]."
        result["citations"] = [999]


def request_task(client, source_id, task):
    _, method, path, payload = next(item for item in api_requests(source_id) if item[0] == task)
    return client.request(method, path, json=payload)


@pytest.mark.parametrize("task", TASKS)
def test_each_capability_reaches_ollama_over_http(ollama_api, task):
    client, state, source_id = ollama_api
    response = request_task(client, source_id, task)
    assert response.status_code == 200, response.text
    assert [call["task"] for call in state["calls"]] == [task]
    assert response.json()["mode"] == "ollama"


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("failure", ["http", "invalid_json", "invalid_reference"])
def test_model_failures_return_502_without_silent_rule_fallback(ollama_api, task, failure):
    client, state, source_id = ollama_api
    state["failure"] = failure
    response = request_task(client, source_id, task)
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"]
    assert [call["task"] for call in state["calls"]] == [task]


def test_reading_preserves_every_character_despite_reordered_model_sections(ollama_api):
    client, state, source_id = ollama_api
    response = request_task(client, source_id, "reading")
    assert response.status_code == 200, response.text
    sections = response.json()["sections"]
    assert len(sections) > 1
    assert [section["index"] for section in sections] == list(range(len(sections)))
    assert "".join(section["text"] for section in sections) == SOURCE_TEXT
    assert state["calls"][0]["input"]["sections"][0]["text"] == sections[0]["text"]


def test_companion_uses_same_model_and_never_reviews_with_its_own_source(ollama_api):
    client, state, source_id = ollama_api
    response = client.post(
        "/api/v1/companion/run",
        json={
            "source_id": source_id,
            "tasks": ["reading", "cards", "facts", "author"],
            "question": "How should I practice active recall?",
            "claims": [CLAIM],
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [call["task"] for call in state["calls"]] == ["reading", "cards", "facts", "author"]
    fact_payload = next(call["input"] for call in state["calls"] if call["task"] == "facts")
    assert fact_payload["evidence"]
    assert all(item["source_id"] != source_id for item in fact_payload["evidence"])
    assert all(item["source_id"] != source_id for item in result["facts"]["reviews"][0]["evidence"])
    assert all(result[name]["mode"] == "ollama" for name in ["reading", "cards", "facts", "author"])
    assert result["author"]["citations"][0]["source_id"] == source_id


def test_grounded_model_cards_still_export_to_anki(ollama_api):
    client, _state, source_id = ollama_api
    generated = request_task(client, source_id, "cards")
    assert generated.status_code == 200, generated.text
    cards = generated.json()["cards"]
    assert all(card["source_id"] == source_id for card in cards)
    exported = client.post("/api/v1/cards/export/apkg", json={"cards": cards})
    assert exported.status_code == 200, exported.text
    assert exported.content[:2] == b"PK"


@pytest.mark.parametrize(
    "successful,validation_failure", [(0, False), (1, False), (5, False), (1, True)]
)
def test_live_report_separates_partial_api_success_from_all_checks(
    monkeypatch, tmp_path, capsys, successful, validation_failure
):
    cases = [
        {
            "capability": task,
            "http_status": 200 if index < successful else 502,
            "response_mode": "ollama" if index < successful else None,
            "passed": index < successful and not validation_failure,
        }
        for index, task in enumerate(TASKS)
    ]
    monkeypatch.setattr(sys, "argv", ["ollama_smoke.py", "--live", "--work-root", str(tmp_path)])
    monkeypatch.setattr(ollama_smoke, "application", lambda *_args: nullcontext(None))
    monkeypatch.setattr(ollama_smoke, "exercise", lambda _client: cases)
    expected_pass = successful == 5 and not validation_failure
    assert ollama_smoke.main() == (0 if expected_pass else 1)
    report = json.loads(capsys.readouterr().out)
    assert report["live_ollama_api_success_count"] == successful
    assert report["live_ollama_api_response_received"] is (successful > 0)
    assert report["all_capabilities_passed"] is expected_pass
    assert report["live_model_validation_passed"] is expected_pass
