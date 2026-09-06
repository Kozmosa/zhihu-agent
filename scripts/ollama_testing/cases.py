"""Exercise all five public capabilities and validate user-visible invariants."""

import time

import httpx

from .fixtures import CLAIM, IMPORT_BODY, SOURCE_TEXT, api_requests


def check_result(task, result, source_id, known_sources):
    assert result["mode"] == "ollama", "Capability did not report Ollama mode"
    if task == "reading":
        sections = result["sections"]
        assert sections and result["summary"]
        assert "".join(item["text"] for item in sections) == SOURCE_TEXT
        return {"sections": len(sections), "original_text_preserved": True}
    if task == "cards":
        cards = result["cards"]
        assert 1 <= len(cards) <= 2, "No usable cards returned for the demonstration text"
        assert all(card["source_id"] == source_id for card in cards)
        assert all(card["evidence_excerpt"] in SOURCE_TEXT for card in cards)
        return {"cards": len(cards), "evidence_excerpts_verified": True}
    if task == "author":
        assert result["answer"] and result["citations"]
        assert all(item["source_id"] in known_sources for item in result["citations"])
        return {"citations": len(result["citations"]), "sources_verified": True}
    if task == "facts":
        reviews = result["reviews"]
        assert len(reviews) == 1 and reviews[0]["claim"] == CLAIM
        assert all(item["source_id"] in known_sources for item in reviews[0]["evidence"])
        return {"status": reviews[0]["status"], "evidence": len(reviews[0]["evidence"])}
    concepts = [node for node in result["nodes"] if node["data"]["kind"] == "concept"]
    assert concepts, "No concept nodes returned for the demonstration text"
    node_ids = {node["id"] for node in result["nodes"]}
    assert all(
        edge["source"] in node_ids and edge["target"] in node_ids for edge in result["edges"]
    )
    for node in concepts:
        assert node["data"]["evidence"]
        assert all(item["source_id"] in known_sources for item in node["data"]["evidence"])
    return {"concepts": len(concepts), "edges": len(result["edges"]), "sources_verified": True}


def exercise(client):
    imported = client.post("/api/v1/sources/import", json=IMPORT_BODY)
    imported.raise_for_status()
    sources = imported.json()
    source_id = sources[0]["id"]
    known_sources = {item["id"] for item in sources}
    results = []
    for task, method, path, payload in api_requests(source_id):
        started = time.monotonic()
        case = {"capability": task, "method": method, "path": path, "passed": False}
        try:
            response = client.request(method, path, json=payload)
            case["http_status"] = response.status_code
            if response.status_code != 200:
                # The application uses a sanitized structured error, not upstream response text.
                case["error_code"] = response.json().get("error", {}).get("code", "http_error")
            else:
                result = response.json()
                case["response_mode"] = result.get("mode")
                case["checks"] = check_result(task, result, source_id, known_sources)
                case["passed"] = True
        except (AssertionError, KeyError, ValueError, TypeError, httpx.HTTPError) as error:
            case["error_type"] = type(error).__name__
        case["seconds"] = round(time.monotonic() - started, 3)
        results.append(case)
    return results
