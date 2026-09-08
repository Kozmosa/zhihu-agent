import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.features.companion.service import CompanionService
from zhijing.features.reader.generation import GeneratedReading
from zhijing.features.runs import service as run_module
from zhijing.features.runs.service import RunService
from zhijing.infrastructure.sqlite_runs import SQLiteRunRepository

TASKS = ["reading", "cards", "facts", "author", "knowledge"]


def body(imported, **kwargs):
    return {"source_id": imported[0]["id"], **kwargs}


def create(client, payload, key="run-test"):
    return client.post("/api/v1/runs", json=payload, headers={"Idempotency-Key": key})


def service(client):
    return client.app.state.runtime.current.container.runs


def test_five_capabilities_persist_and_idempotency_prevents_reexecution(
    client, imported, monkeypatch
):
    payload = body(
        imported,
        tasks=TASKS,
        question="如何主动回忆？",
        claims=["主动回忆是尝试在不看原文的情况下回想所学内容。"],
    )
    calls = []
    original = CompanionService.execute

    def execute(self, request, task):
        calls.append(task)
        return original(self, request, task)

    monkeypatch.setattr(CompanionService, "execute", execute)
    response = create(client, payload)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded"
    assert all(run["result"][task] is not None for task in TASKS)
    assert calls == TASKS
    assert all(step["attempts"] == 1 for step in run["steps"])
    assert client.get(f"/api/v1/runs/{run['id']}").json() == run
    assert create(client, payload).json() == run
    assert calls == TASKS
    assert all(
        evidence["source_id"] != payload["source_id"]
        for review in run["result"]["facts"]["reviews"]
        for evidence in review["evidence"]
    )


def test_companion_legacy_endpoint_includes_knowledge(client, imported):
    response = client.post("/api/v1/companion/run", json=body(imported, tasks=["knowledge"]))
    assert response.status_code == 200
    assert response.json()["knowledge"]["total_sources"] == 2


def test_prepare_execute_and_page_does_not_load_full_results(client, imported):
    run = create(client, body(imported, prepare_only=True)).json()
    assert run["status"] == "pending" and run["attempts"] == 0
    assert all(step["status"] == "pending" for step in run["steps"])
    assert client.post(f"/api/v1/runs/{run['id']}/execute").json()["status"] == "succeeded"
    second = create(client, body(imported, prepare_only=True), "second").json()
    page = client.get("/api/v1/runs", params={"limit": 1}).json()
    assert page["total"] == 2 and page["has_more"]
    assert page["items"][0]["id"] == second["id"]
    assert "result" not in page["items"][0] and "request" not in page["items"][0]
    assert client.get("/api/v1/runs", params={"status": "pending"}).json()["total"] == 1
    assert client.get("/api/v1/runs", params={"source_id": "unknown"}).json()["total"] == 0
    assert client.get("/api/v1/runs", params={"offset": 2**63}).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"tasks": ["author"]},
        {"tasks": ["facts"]},
        {"tasks": ["reading", "reading"]},
        {"tasks": ["unknown"]},
        {"max_attempts": 6},
        {"timeout_seconds": 0},
        {"knowledge_scope": "unknown"},
        {"api_key": "never-store-this"},
    ],
)
def test_invalid_requests_leave_no_runs(client, imported, changes):
    response = create(client, body(imported, **changes))
    assert response.status_code == 422
    assert client.get("/api/v1/runs").json()["total"] == 0


def test_required_key_and_conflict(client, imported):
    payload = body(imported, prepare_only=True)
    assert client.post("/api/v1/runs", json=payload).status_code == 422
    assert create(client, payload, "bad key").status_code == 422
    assert create(client, payload).status_code == 200
    response = create(client, {**payload, "tasks": ["cards"]})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
    assert client.get("/api/v1/runs").json()["total"] == 1


def test_partial_failure_retry_preserves_results_and_model_provenance(
    client, imported, monkeypatch
):
    original = CompanionService.execute
    calls = []
    failing = True

    def execute(self, request, task):
        calls.append(task)
        if task == "cards" and failing:
            raise DomainError("model_unavailable", "SECRET https://upstream?key=SECRET", 502)
        return original(self, request, task)

    monkeypatch.setattr(CompanionService, "execute", execute)
    run = create(client, body(imported)).json()
    assert run["status"] == "partial"
    assert run["result"]["reading"] and run["result"]["knowledge"]
    assert run["result"]["cards"] is None
    assert "SECRET" not in json.dumps(run)
    failing = False
    previous = service(client)
    retry_service = RunService(
        previous.repository, previous.companion, provider="openai", model="ds-test"
    )
    updated = retry_service.retry(run["id"]).model_dump(mode="json")
    assert updated["status"] == "succeeded"
    assert calls == ["reading", "cards", "knowledge", "cards"]
    assert updated["result"]["reading"] == run["result"]["reading"]
    assert updated["steps"][0]["provider"] == "extractive"
    assert updated["steps"][1]["provider"] == "openai"
    assert updated["steps"][1]["model"] == "ds-test"
    assert updated["steps"][1]["attempts"] == 2
    assert updated["provider"] == "extractive"
    assert client.post(f"/api/v1/runs/{run['id']}/retry").status_code == 409


def test_retry_limit_and_safe_unknown_error(client, imported, monkeypatch):
    def fail(self, request, task):
        raise RuntimeError("SECRET https://private-api.test")

    monkeypatch.setattr(CompanionService, "execute", fail)
    run = create(client, body(imported, tasks=["reading"], max_attempts=2)).json()
    assert run["status"] == "failed" and "SECRET" not in json.dumps(run)
    response = client.post(f"/api/v1/runs/{run['id']}/retry")
    assert response.json()["attempts"] == 2
    response = client.post(f"/api/v1/runs/{run['id']}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_attempts_exhausted"


@pytest.mark.parametrize("code", ["model_timeout", "model_batch_limit"])
def test_model_failure_categories_preserved_without_upstream_message(
    client, imported, monkeypatch, code
):
    def fail(self, request, task):
        raise DomainError(code, "SECRET raw upstream response", 502)

    monkeypatch.setattr(CompanionService, "execute", fail)
    run = create(client, body(imported, tasks=["reading"])).json()
    assert run["status"] == "failed"
    assert run["steps"][0]["error"]["code"] == code
    assert "SECRET" not in json.dumps(run)


def test_pending_cancel_retry_and_missing_run(client, imported):
    run = create(client, body(imported, prepare_only=True)).json()
    response = client.post(f"/api/v1/runs/{run['id']}/cancel")
    assert response.json()["status"] == "cancelled"
    assert client.post(f"/api/v1/runs/{run['id']}/execute").status_code == 409
    assert client.post(f"/api/v1/runs/{run['id']}/retry").json()["status"] == "succeeded"
    for method, suffix in [
        ("get", ""),
        ("post", "/execute"),
        ("post", "/cancel"),
        ("post", "/retry"),
    ]:
        assert getattr(client, method)("/api/v1/runs/missing" + suffix).status_code == 404


def test_running_run_query_cancel_and_concurrent_execute(client, imported, monkeypatch):
    started, release = Event(), Event()
    original = CompanionService.execute

    def execute(self, request, task):
        if task == "reading":
            started.set()
            assert release.wait(10)
        return original(self, request, task)

    monkeypatch.setattr(CompanionService, "execute", execute)
    run = create(client, body(imported, prepare_only=True)).json()
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(client.post, f"/api/v1/runs/{run['id']}/execute")
        try:
            assert started.wait(10)
            assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "running"
            assert client.post(f"/api/v1/runs/{run['id']}/execute").status_code == 409
            assert client.post(f"/api/v1/runs/{run['id']}/retry").status_code == 409
            assert client.post(f"/api/v1/runs/{run['id']}/cancel").json()["cancel_requested"]
        finally:
            release.set()
        completed = running.result(timeout=10).json()
    assert completed["status"] == "cancelled"
    assert completed["steps"][1]["attempts"] == 0


def test_timeout_preserves_completed_steps_and_retry_resumes(client, imported, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(run_module, "monotonic", lambda: clock[0])
    original = CompanionService.execute

    def execute(self, request, task):
        result = original(self, request, task)
        if task == "cards":
            clock[0] += 2
        return result

    monkeypatch.setattr(CompanionService, "execute", execute)
    run = create(client, body(imported, timeout_seconds=1)).json()
    assert run["status"] == "timed_out"
    assert run["steps"][0]["status"] == "succeeded"
    assert run["steps"][1]["error"]["code"] == "run_timeout"
    assert run["steps"][2]["attempts"] == 0
    monkeypatch.setattr(CompanionService, "execute", original)
    resumed = client.post(f"/api/v1/runs/{run['id']}/retry").json()
    assert resumed["status"] == "succeeded"
    assert resumed["steps"][0]["attempts"] == 1


def test_cancel_checks_after_model_call_before_step_commit(client, imported):
    runs = service(client)
    run = create(client, body(imported, tasks=["reading", "cards"], prepare_only=True)).json()

    class CancellingGenerator:
        mode = "ollama"

        def generate(self, *, payload, **kwargs):
            runs.cancel(run["id"])
            return GeneratedReading(
                summary="summary",
                sections=[
                    {
                        "index": section["index"],
                        "heading": "heading",
                        "key_points": ["point"],
                        "guiding_question": "question",
                    }
                    for section in payload["sections"]
                ],
            )

    runs.companion.reader.generator = CancellingGenerator()
    response = client.post(f"/api/v1/runs/{run['id']}/execute").json()
    assert response["status"] == "cancelled"
    assert response["result"]["reading"] is None
    assert response["steps"][1]["attempts"] == 0


def test_cancel_between_final_checkpoint_and_commit_wins_terminal_state(
    client, imported, monkeypatch
):
    runs = service(client)
    original = runs.repository.mutate

    def mutate(run_id, change):
        if change.__name__ == "complete_step":
            runs.cancel(run_id)
        return original(run_id, change)

    monkeypatch.setattr(runs.repository, "mutate", mutate)
    run = create(client, body(imported, tasks=["reading"])).json()
    assert run["cancel_requested"]
    assert run["status"] == "cancelled"
    # A completed result may be retained, but an accepted cancellation cannot
    # disappear from the terminal workflow state.
    assert run["result"]["reading"] is not None


def test_frozen_corpus_ignores_later_imports_and_library_scope_is_explicit(
    client, imported, sample
):
    payload = body(imported, tasks=["knowledge"], prepare_only=True, knowledge_scope="library")
    run = create(client, payload).json()
    new_source = {
        **sample["items"][0],
        "title": "later import",
        "text": "新增材料不属于工作流原始快照。",
    }
    client.post("/api/v1/sources/import", json={"items": [new_source]})
    completed = client.post(f"/api/v1/runs/{run['id']}/execute").json()
    assert len(completed["source_ids"]) == 3
    assert completed["result"]["knowledge"]["total_sources"] == 3
    assert client.get("/api/v1/knowledge-map").json()["total_sources"] == 4


def test_restart_recovers_running_but_preserves_pending_and_results(tmp_path, sample):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as first:
        imported = first.post("/api/v1/sources/import", json=sample).json()
        pending = create(first, body(imported, prepare_only=True), "pending").json()
        interrupted = create(first, body(imported, prepare_only=True), "interrupted").json()
        completed = create(first, body(imported), "completed").json()
        runs = service(first)
        runs._claim(interrupted["id"], retry=False)

        def mark_step(run):
            run.steps[0].status = "running"
            run.steps[0].attempts = 1

        runs.repository.mutate(interrupted["id"], mark_step)
        # Rebuilding storage for a model switch must never perform crash recovery.
        SQLiteRunRepository(tmp_path / "runs.sqlite3").initialize()
        assert runs.get(interrupted["id"]).status == "running"
    with TestClient(create_app(settings)) as second:
        assert second.get(f"/api/v1/runs/{pending['id']}").json()["status"] == "pending"
        recovered = second.get(f"/api/v1/runs/{interrupted['id']}").json()
        assert recovered["status"] == "interrupted"
        assert recovered["steps"][0]["error"]["code"] == "process_interrupted"
        assert second.get(f"/api/v1/runs/{completed['id']}").json() == completed
        assert (
            second.post(f"/api/v1/runs/{interrupted['id']}/retry").json()["status"] == "succeeded"
        )
    connection = sqlite3.connect(tmp_path / "runs.sqlite3")
    try:
        raw = " ".join(str(row) for row in connection.execute("SELECT key_hash, payload FROM runs"))
        assert "Idempotency-Key" not in raw and "api_key" not in raw
    finally:
        connection.close()


@pytest.mark.parametrize(
    "model", ["https://api.test/key", "sk-secret", "Bearer-secret", "name?api_key=secret"]
)
def test_configuration_metadata_rejects_secret_like_model_names(client, model):
    runs = service(client)
    redacted = RunService(runs.repository, runs.companion, provider="openai", model=model)
    assert redacted.model == "[redacted]"
