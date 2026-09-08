"""Run five independent public API checks without modifying the user's application data."""

import re
import tempfile
import time
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings

from .fixtures import CLAIM, IMPORT_BODY, SOURCE_TEXT, api_requests, model_response
from .mock_server import mock_model

CAPABILITIES = ("reading", "cards", "facts", "knowledge", "author")


class CheckFailure(Exception):
    """The argument is a fixed public reason code, never model-generated content."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


class TransportProbe:
    """Observe transport counters without retaining potentially sensitive HTTP objects."""

    def __init__(self):
        self.requests = self.responses = self.successes = 0

    def request(self, _request):
        self.requests += 1

    def response(self, response):
        self.responses += 1
        self.successes += int(response.is_success)

    def snapshot(self):
        return self.requests, self.responses, self.successes

    def since(self, before, provider):
        requests, responses, successes = (
            current - previous for current, previous in zip(self.snapshot(), before, strict=True)
        )
        return {
            "applicable": provider != "extractive",
            "requests": requests,
            "http_responses": responses,
            "http_successes": successes,
            "http_response_received": responses > 0,
            "http_success_received": successes > 0,
        }


def _check_citations(citations, source_texts):
    require(bool(citations), "missing_evidence")
    for citation in citations:
        source_id = citation["source_id"]
        require(source_id in source_texts, "unknown_evidence_source")
        excerpt = citation["excerpt"]
        require(bool(excerpt) and excerpt in source_texts[source_id], "invalid_evidence_excerpt")


def check_result(task, result, provider, source_id, source_texts, *, max_cards=2):
    require(result.get("mode") == provider, "unexpected_provider_mode")
    if task == "reading":
        sections = result["sections"]
        require(bool(sections) and bool(result["summary"]), "missing_reading_output")
        require("".join(item["text"] for item in sections) == SOURCE_TEXT, "original_text_changed")
        return {"sections": len(sections), "original_text_preserved": True}
    if task == "cards":
        cards = result["cards"]
        require(1 <= len(cards) <= max_cards, "unusable_card_count")
        for card in cards:
            require(card["source_id"] == source_id, "unexpected_card_source")
            require(bool(card["front"]) and bool(card["back"]), "empty_card")
            if provider != "extractive":
                excerpt = card["evidence_excerpt"]
                require(bool(excerpt) and excerpt in SOURCE_TEXT, "invalid_card_evidence")
            else:
                require(card["back"] in SOURCE_TEXT, "invalid_extractive_card")
        return {"cards": len(cards), "source_grounding_verified": True}
    if task == "author":
        require(bool(result["answer"]), "empty_author_answer")
        _check_citations(result["citations"], source_texts)
        return {"citations": len(result["citations"]), "evidence_excerpts_verified": True}
    if task == "facts":
        reviews = result["reviews"]
        require(len(reviews) == 1 and reviews[0]["claim"] == CLAIM, "unexpected_fact_claim")
        _check_citations(reviews[0]["evidence"], source_texts)
        return {"reviews": len(reviews), "evidence_excerpts_verified": True}
    nodes, edges = result["nodes"], result["edges"]
    require(bool(nodes), "empty_knowledge_map")
    node_ids = {node["id"] for node in nodes}
    require(
        all(edge["source"] in node_ids and edge["target"] in node_ids for edge in edges),
        "invalid_graph_endpoint",
    )
    if provider != "extractive":
        concepts = [node for node in nodes if node["data"]["kind"] == "concept"]
        require(bool(concepts), "empty_model_concepts")
        for node in concepts:
            _check_citations(node["data"]["evidence"], source_texts)
        for edge in edges:
            if edge.get("data"):
                _check_citations(edge["data"]["evidence"], source_texts)
    else:
        answers = [node for node in nodes if node["data"]["kind"] == "answer"]
        require(bool(answers), "missing_source_nodes")
        require(
            all(node["data"]["source_id"] in source_texts for node in answers),
            "unknown_graph_source",
        )
    return {"nodes": len(nodes), "edges": len(edges), "graph_integrity_verified": True}


def new_report(provider, mode):
    return {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "mode": "extractive" if provider == "extractive" else mode,
        "synthetic_input": True,
        "mock_responses": provider != "extractive" and mode == "mock",
        "quality_status": "not_evaluated",
        "notice": (
            "Synthetic smoke checks verify transport, schema, source provenance and application "
            "invariants. They do not measure semantic quality, truth, or general model reliability. "
            "No model is admitted for production quality by this report."
        ),
        "admission_scope": "synthetic_five_capability_smoke_only",
        "admission": "not_evaluated",
        "all_capabilities_passed": False,
        "live_model_validation_passed": False,
        "cases": [
            {
                "capability": task,
                "status": "not_run",
                "passed": False,
                "application_validation_passed": False,
                "response_mode": None,
                "reason": "setup_incomplete",
            }
            for task in CAPABILITIES
        ],
        "passed": False,
    }


def _safe_error_code(value):
    # Error messages, URLs, exception text and upstream response bodies are never reported.
    allowed = {
        "model_timeout",
        "model_unavailable",
        "model_invalid_response",
        "model_input_too_large",
        "model_context_exceeded",
        "model_batch_limit",
        "source_not_found",
        "invalid_request",
        "validation_error",
    }
    return value if isinstance(value, str) and value in allowed else "application_http_error"


def exercise(client, provider, probe, cases):
    imported = client.post("/api/v1/sources/import", json=IMPORT_BODY)
    require(imported.status_code == 200, "fixture_import_failed")
    sources = imported.json()
    source_id = sources[0]["id"]
    source_texts = {source["id"]: source["text"] for source in sources}
    for index, (task, method, path, payload) in enumerate(api_requests(source_id)):
        started, before = time.monotonic(), probe.snapshot()
        case = cases[index]
        case["status"] = "failed"
        try:
            response = client.request(method, path, json=payload)
            case["http_status"] = response.status_code
            if response.status_code != 200:
                body = response.json()
                case["reason"] = _safe_error_code(body.get("error", {}).get("code"))
            else:
                result = response.json()
                actual_mode = result.get("mode")
                case["response_mode"] = (
                    actual_mode if actual_mode in {"extractive", "ollama", "openai"} else "unknown"
                )
                case["checks"] = check_result(task, result, provider, source_id, source_texts)
                case.update(
                    status="passed",
                    passed=True,
                    application_validation_passed=True,
                    reason="application_and_fixture_invariants_passed",
                )
        except CheckFailure as error:
            case["reason"] = str(error)
        except Exception as error:
            # Continue the other four checks even after an application bug or a timeout.
            case["reason"] = "capability_check_exception"
            case["error_type"] = type(error).__name__
        case["transport"] = probe.since(before, provider)
        case["seconds"] = round(time.monotonic() - started, 3)
    return source_id, source_texts


def run_verification(
    settings: Settings,
    *,
    mode: str,
    work_root: Path | None = None,
    responder=model_response,
    include_workflow: bool = False,
):
    """Return a secret-free report. Real endpoints require mode='live' explicitly."""
    provider = settings.model_provider
    report = new_report(provider, mode)
    report["workflow"] = {
        "requested": include_workflow,
        "status": "not_run" if include_workflow else "not_requested",
    }
    probe = TransportProbe()
    try:
        require(provider in {"extractive", "ollama", "openai"}, "unsupported_provider")
        require(mode in {"mock", "live", "extractive"}, "unsupported_verification_mode")
        require(
            provider == "extractive" or mode in {"mock", "live"}, "explicit_model_mode_required"
        )
        if work_root is not None:
            work_root = Path(work_root).resolve()
            work_root.mkdir(parents=True, exist_ok=True)
        context = (
            mock_model(provider, responder)
            if provider != "extractive" and mode == "mock"
            else nullcontext((None, None))
        )
        with context as (mock_url, calls):
            with tempfile.TemporaryDirectory(prefix="zhijing-verify-", dir=work_root) as name:
                data_dir = Path(name).resolve()
                require(work_root is None or data_dir.is_relative_to(work_root), "unsafe_work_path")
                active = replace(settings, data_dir=data_dir)
                if mock_url is not None:
                    active = replace(
                        active,
                        **{
                            f"{provider}_url": mock_url,
                            f"{provider}_api_key": "",
                            f"{provider}_model": "synthetic-fixture",
                        },
                    )
                require(not active.validation_errors(), "invalid_configuration")
                if provider != "extractive":
                    model = getattr(active, f"{provider}_model")
                    report["model"] = (
                        model
                        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,127}", model)
                        and "://" not in model
                        and not model.lower().startswith(("sk-", "bearer"))
                        and model != getattr(active, f"{provider}_api_key")
                        else "redacted"
                    )
                with TestClient(create_app(active)) as client:
                    with client.app.state.runtime.lease() as container:
                        if container.model_client is not None:
                            container.model_client.event_hooks["request"].append(probe.request)
                            container.model_client.event_hooks["response"].append(probe.response)
                    source_id, source_texts = exercise(client, provider, probe, report["cases"])
                    if include_workflow:
                        from .workflow import exercise_workflow

                        report["workflow"] = exercise_workflow(
                            client, provider, probe, source_id, source_texts
                        )
            if calls is not None:
                report["mock_model_calls"] = calls
    except CheckFailure as error:
        report["reason"] = str(error)
    except Exception as error:
        report["reason"] = "verification_setup_exception"
        report["error_type"] = type(error).__name__
    report["transport"] = probe.since((0, 0, 0), provider)
    report["all_capabilities_passed"] = all(case["passed"] for case in report["cases"])
    report["passed"] = (
        report["all_capabilities_passed"]
        and "reason" not in report
        and (not include_workflow or report["workflow"]["status"] == "passed")
    )
    report["live_model_validation_passed"] = (
        provider != "extractive" and mode == "live" and report["passed"]
    )
    report["admission"] = "smoke_passed" if report["passed"] else "rejected"
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report
