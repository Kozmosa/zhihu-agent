"""Optional durable five-step workflow acceptance using the same synthetic corpus."""

import time

from .fixtures import CLAIM
from .runner import CAPABILITIES, CheckFailure, check_result, require


def exercise_workflow(client, provider, probe, source_id, source_texts):
    started, before = time.monotonic(), probe.snapshot()
    report = {"requested": True, "status": "failed", "steps": []}
    payload = {
        "source_id": source_id,
        "tasks": ["reading", "cards", "facts", "author", "knowledge"],
        "claims": [CLAIM],
        "question": "How should I practice active recall?",
        "knowledge_scope": "author",
    }
    headers = {"Idempotency-Key": "synthetic-verification-five-capability-run"}
    try:
        response = client.post("/api/v1/runs", json=payload, headers=headers)
        report["http_status"] = response.status_code
        require(response.status_code == 200, "workflow_http_error")
        record = response.json()
        require(
            set(step["task"] for step in record["steps"]) == set(CAPABILITIES),
            "workflow_missing_steps",
        )
        for step in record["steps"]:
            task = step["task"]
            item = {"task": task, "status": "failed", "response_mode": None}
            try:
                require(step["status"] == "succeeded", "workflow_step_failed")
                result = record["result"][task]
                mode = result.get("mode")
                item["response_mode"] = (
                    mode if mode in {"extractive", "ollama", "openai"} else "unknown"
                )
                item["checks"] = check_result(
                    task, result, provider, source_id, source_texts, max_cards=5
                )
                item["status"] = "passed"
            except CheckFailure as error:
                item["reason"] = str(error)
            except Exception as error:
                item.update(reason="workflow_step_check_exception", error_type=type(error).__name__)
            report["steps"].append(item)
        require(record["status"] == "succeeded", "workflow_not_succeeded")
        require(
            all(step["status"] == "passed" for step in report["steps"]), "workflow_output_invalid"
        )
        loaded = client.get(f"/api/v1/runs/{record['id']}")
        require(loaded.status_code == 200 and loaded.json() == record, "workflow_readback_mismatch")
        report["persisted_result_reloaded"] = True
        calls_before_replay = probe.snapshot()
        replay = client.post("/api/v1/runs", json=payload, headers=headers)
        require(replay.status_code == 200 and replay.json() == record, "workflow_replay_mismatch")
        require(probe.snapshot() == calls_before_replay, "workflow_replay_called_model")
        report.update(status="passed", idempotent_replay_without_model_calls=True)
    except CheckFailure as error:
        report["reason"] = str(error)
    except Exception as error:
        report.update(reason="workflow_check_exception", error_type=type(error).__name__)
    report["transport"] = probe.since(before, provider)
    report["seconds"] = round(time.monotonic() - started, 3)
    return report
