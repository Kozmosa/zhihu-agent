"""Exercise provider envelopes through the actual card API and export boundary."""

import json
from types import SimpleNamespace

import httpx
import pytest

from zhijing.dependencies import get_container
from zhijing.features.cards.service import CardService
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator

EVIDENCE = "主动回忆是合上书主动提取所学内容。"
GOOD = {"front": "什么是主动回忆？", "back": "合上书，主动提取所学。", "evidence_excerpt": EVIDENCE}


@pytest.fixture(params=["ollama", "openai"])
def provider(client, request, tmp_path):
    replies, calls = [], []

    def respond(http_request):
        calls.append(http_request)
        content, reason = replies.pop(0)
        envelope = (
            {"choices": [{"message": {"content": content}, "finish_reason": reason}]}
            if request.param == "openai"
            else {"response": content, "done": True, "done_reason": reason}
        )
        return httpx.Response(200, json=envelope)

    with httpx.Client(
        base_url="http://model.invalid/", transport=httpx.MockTransport(respond)
    ) as http:
        generator_type = OpenAICompatibleGenerator if request.param == "openai" else OllamaGenerator
        source = SimpleNamespace(id="source-test", title="主动回忆", text=EVIDENCE)
        service = CardService(
            SimpleNamespace(get=lambda _: source), generator_type(http, "fixture")
        )
        client.app.dependency_overrides[get_container] = lambda: SimpleNamespace(
            cards=service, export_dir=tmp_path
        )

        def generate(content, reason="stop", count=5):
            replies.append((content, reason))
            return client.post(
                "/api/v1/cards/generate", json={"source_id": source.id, "count": count}
            )

        yield generate, client, calls, request.param
        client.app.dependency_overrides.clear()


def test_valid_cards_survive_bad_format_duplicate_and_fabricated_evidence(provider):
    generate, client, calls, mode = provider
    content = json.dumps(
        {
            "cards": [
                {**GOOD, "front": "x" * 161},
                GOOD,
                GOOD,
                {**GOOD, "front": "能永不遗忘吗？", "evidence_excerpt": "保证永不遗忘。"},
                {**GOOD, "source_id": "model-invented"},
            ]
        },
        ensure_ascii=False,
    )
    response = generate("```json\n" + content + "\n```")
    assert response.status_code == 200
    result = response.json()
    assert result["mode"] == mode
    assert len(result["cards"]) == 1
    assert result["cards"][0]["source_id"] == "source-test"
    assert result["cards"][0]["evidence_excerpt"] == EVIDENCE
    assert "已跳过 4 张" in result["notice"]
    assert len(calls) == 1  # No hidden paid retries or template fallback.
    for kind in ("tsv", "apkg"):
        exported = client.post(f"/api/v1/cards/export/{kind}", json={"cards": result["cards"]})
        assert exported.status_code == 200 and exported.content
        assert (
            ("source-test" in exported.text)
            if kind == "tsv"
            else exported.content.startswith(b"PK")
        )


@pytest.mark.parametrize(
    "content",
    [
        '{"cards": [',
        'Reasoning first\n{"cards": []}',
        '{"cards": [], "source_id": "bad"}',
        '{"cards": {}}',
        json.dumps({"cards": [{**GOOD, "source_id": "bad"}]}),
        json.dumps({"cards": [{**GOOD, "front": GOOD["back"]}]}),
    ],
)
def test_bad_output_is_actionable_without_echoing_model_text(provider, content):
    generate, _, calls, _ = provider
    response = generate(content)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "cards_format_invalid"
    assert "Reasoning first" not in response.text and "source_id" not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("content", [None, "", '{"cards": [', json.dumps({"cards": [GOOD]})])
def test_length_finish_reason_never_exports_even_valid_looking_json(provider, content):
    generate, _, calls, _ = provider
    response = generate(content, reason="length")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "model_output_truncated"
    assert len(calls) == 1


def test_unique_excess_cards_are_limited_to_request(provider):
    generate, _, _, _ = provider
    response = generate(json.dumps({"cards": [GOOD, {**GOOD, "front": "怎样主动回忆？"}]}), count=1)
    assert response.status_code == 200
    assert len(response.json()["cards"]) == 1


def test_fabricated_evidence_remains_a_visible_failure(provider):
    generate, _, _, _ = provider
    response = generate(json.dumps({"cards": [{**GOOD, "evidence_excerpt": "保证永不遗忘。"}]}))
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "cards_evidence_invalid"
