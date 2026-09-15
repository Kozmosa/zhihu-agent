"""Long Chinese documents exercise real provider budgets through mock transports."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from zhijing.core.errors import DomainError
from zhijing.core.text import chunks
from zhijing.domain.models import Source
from zhijing.features.cards.generation import CARDS_INSTRUCTIONS, GeneratedCards
from zhijing.features.cards.schemas import CardRequest
from zhijing.features.cards.service import CardService
from zhijing.features.knowledge.generation import build_model_graph
from zhijing.features.reader.generation import READING_INSTRUCTIONS, GeneratedReading
from zhijing.features.reader.schemas import ReadingRequest
from zhijing.features.reader.service import ReaderService
from zhijing.infrastructure.batching import budget_batches
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator


def chinese_text(size):
    sentence = "主动回忆帮助检查理解缺口，间隔复习需要根据掌握程度调整。"
    # Count the requested amount of actual Chinese characters, plus separators.
    chinese = sentence.replace("，", "").replace("。", "")
    text = (chinese * (size // len(chinese) + 1))[:size]
    document = " \n" + "。\n".join(text[index : index + 97] for index in range(0, size, 97)) + "\n "
    return document[:100_000]


def source_for(text):
    return Source(
        id="source-long",
        title="长文学习资料",
        author_id="author-long",
        author_name="作者",
        text=text,
        created_at="2026-09-08T00:00:00Z",
    )


def reply_for(task, payload, call_index):
    if task == "reading":
        return {
            "summary": f"本批摘要 {call_index}",
            "sections": [
                {
                    "index": item["index"],
                    "heading": "主动回忆",
                    "key_points": ["用回忆检查理解。"],
                    "guiding_question": "如何检查理解缺口？",
                }
                for item in reversed(payload["sections"])
            ],
        }
    if task == "cards":
        evidence = payload["text"].strip()[:20]
        return {
            "cards": [
                {
                    "front": question,
                    "back": "根据掌握程度调整复习。",
                    "evidence_excerpt": evidence,
                }
                for question in ["共同问题？", f"本批独立问题 {call_index}？"][: payload["count"]]
            ]
        }
    evidence_ids = [item["evidence_id"] for item in payload["evidence"]]
    return {
        "nodes": [
            {
                "id": "recall",
                "label": "主动回忆",
                "description": "主动提取学习内容检查理解。",
                "evidence_ids": evidence_ids,
            },
            {
                "id": "review",
                "label": "间隔复习",
                "description": "根据掌握程度调整复习。",
                "evidence_ids": evidence_ids,
            },
        ],
        "edges": [
            {
                "id": "relation",
                "source": "recall",
                "target": "review",
                "relation": "supplements",
                "explanation": "回忆检查可辅助调整复习。",
                "evidence_ids": evidence_ids,
            }
        ],
    }


@contextmanager
def model_mock(provider="ollama", responder=reply_for, **kwargs):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        prompt = json.loads(
            body["prompt"] if provider == "ollama" else body["messages"][1]["content"]
        )
        calls.append(prompt)
        output = json.dumps(
            responder(prompt["task"], prompt["input"], len(calls)), ensure_ascii=False
        )
        response = (
            {"response": output, "done": True}
            if provider == "ollama"
            else {"choices": [{"message": {"content": output}, "finish_reason": "stop"}]}
        )
        return httpx.Response(200, json=response)

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test/") as client:
        factory = OllamaGenerator if provider == "ollama" else OpenAICompatibleGenerator
        yield factory(client, "mock-model", **kwargs), calls


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("size", [10_000, 30_000, 100_000])
def test_reading_complete_chinese_document_with_real_provider_budget(provider, size):
    text = chinese_text(size)
    with model_mock(provider) as (generator, calls):
        result = ReaderService(None, generator).analyze(ReadingRequest(text=text))
    assert len(calls) > 1
    assert result.mode == provider and result.batch_count == len(calls)
    assert "未经全文综合推断" in result.summary
    assert "".join(section.text for section in result.sections) == text
    assert [section.index for section in result.sections] == list(range(len(chunks(text))))
    supplied = [section for call in calls for section in call["input"]["sections"]]
    assert [item["index"] for item in supplied] == list(range(len(chunks(text))))
    assert "".join(item["text"] for item in supplied) == text
    assert all(f"本批摘要 {index}" in result.summary for index in range(1, len(calls) + 1))


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("size", [10_000, 30_000, 100_000])
def test_cards_cover_all_batches_and_apply_one_global_count(provider, size):
    source = source_for(chinese_text(size))
    repository = SimpleNamespace(get=lambda _: source)
    with model_mock(provider) as (generator, calls):
        result = CardService(repository, generator).generate(
            CardRequest(source_id=source.id, count=5)
        )
    assert len(calls) > 1
    assert "".join(call["input"]["text"] for call in calls) == source.text
    assert len(result.cards) == min(5, len(calls) + 1)
    assert len({card.front for card in result.cards}) == len(result.cards)
    assert result.cards[0].front == "共同问题？"
    assert all(card.source_id == source.id for card in result.cards)
    assert all(card.evidence_excerpt in source.text for card in result.cards)
    assert f"分 {len(calls)} 批" in result.notice


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("size", [10_000, 30_000, 100_000])
def test_graph_merges_batch_local_ids_and_preserves_all_evidence(provider, size):
    source = source_for(chinese_text(size))
    with model_mock(provider) as (generator, calls):
        result = build_model_graph(generator, [source], total_sources=1)
    assert len(calls) > 1
    supplied = [item for call in calls for item in call["input"]["evidence"]]
    assert "".join(item["excerpt"] for item in supplied) == source.text
    assert len({item["evidence_id"] for item in supplied}) == len(chunks(source.text))
    assert [item["chunk_index"] for item in supplied] == list(range(len(chunks(source.text))))
    assert len(result.nodes) == 2 and len(result.edges) == 1
    for node in result.nodes:
        assert len(node.data.evidence) == len(chunks(source.text))
        assert "".join(item.excerpt for item in node.data.evidence) == source.text
        assert all(item.source_id == source.id for item in node.data.evidence)
    edge = result.edges[0]
    assert len(edge.data.evidence) == len(chunks(source.text))
    assert edge.source in {node.id for node in result.nodes}
    assert edge.target in {node.id for node in result.nodes}
    assert "未额外推断跨批关系" in result.analysis_notice
    assert not result.truncated


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_short_documents_keep_one_call_and_original_payload(provider):
    text = "主动回忆帮助检查理解缺口，间隔复习需要调整。"
    with model_mock(provider) as (generator, calls):
        reading = ReaderService(None, generator).analyze(ReadingRequest(text=text))
        source = source_for(text)
        CardService(SimpleNamespace(get=lambda _: source), generator).generate(
            CardRequest(source_id=source.id)
        )
        graph = build_model_graph(generator, [source], 1)
    assert len(calls) == 3
    assert reading.summary == "本批摘要 1" and reading.batch_count == 1
    assert calls[0]["input"] == {"sections": [{"index": 0, "text": text}]}
    assert calls[1]["input"] == {"title": source.title, "text": text, "count": 5}
    assert graph.nodes[0].id == "concept:recall"


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_impossible_schema_budget_fails_before_network(provider):
    with model_mock(provider, max_input_chars=100) as (generator, calls):
        with pytest.raises(DomainError) as error:
            ReaderService(None, generator).analyze(ReadingRequest(text=chinese_text(10_000)))
    assert error.value.code == "model_input_too_large" and error.value.status == 413
    assert calls == []


def test_one_unfit_passage_rejects_all_batches_before_network():
    with model_mock(max_input_chars=3000, num_ctx=100_000) as (generator, calls):
        with pytest.raises(DomainError) as error:
            ReaderService(None, generator).analyze(
                ReadingRequest(text="甲" * 10_000, chunk_size=2000)
            )
    assert error.value.code == "model_input_too_large"
    assert calls == []


@pytest.mark.parametrize("failure_code", ["model_unavailable", "model_input_too_large"])
def test_failure_in_second_generated_batch_is_not_retried_or_downgraded(failure_code):
    failure = DomainError(failure_code, "受控失败", 502)

    def responder(task, payload, index):
        if index == 2:
            raise failure
        return reply_for(task, payload, index)

    with model_mock(responder=responder) as (generator, calls):
        with pytest.raises(DomainError) as error:
            ReaderService(None, generator).analyze(ReadingRequest(text=chinese_text(30_000)))
    assert error.value is failure and len(calls) == 2


def test_non_budget_preflight_error_is_not_split():
    failure = DomainError("model_invalid_response", "不能分批处理此错误", 502)
    checked = []

    def check_budget(**kwargs):
        checked.append(kwargs)
        raise failure

    with pytest.raises(DomainError) as error:
        budget_batches(
            SimpleNamespace(check_budget=check_budget),
            ["甲", "乙", "丙"],
            task="cards",
            instructions=CARDS_INSTRUCTIONS,
            payload_for=lambda batch: {"text": "".join(batch)},
            response_model=GeneratedCards,
        )
    assert error.value is failure and len(checked) == 1


def test_reading_rejects_global_index_from_a_different_batch():
    def responder(task, payload, index):
        response = reply_for(task, payload, index)
        if index == 2:
            response["sections"][0]["index"] = 0
        return response

    with model_mock(responder=responder) as (generator, calls):
        with pytest.raises(DomainError) as error:
            ReaderService(None, generator).analyze(ReadingRequest(text=chinese_text(30_000)))
    assert error.value.code == "model_invalid_response" and len(calls) == 2


def test_cards_reject_evidence_that_only_occurs_in_another_batch():
    source = source_for("仅在开头出现的证据。" + "甲" * 30_000)

    def responder(task, payload, index):
        response = reply_for(task, payload, index)
        if index == 2:
            response["cards"][0]["evidence_excerpt"] = "仅在开头出现的证据。"
        return response

    with model_mock(responder=responder) as (generator, calls):
        with pytest.raises(DomainError) as error:
            CardService(SimpleNamespace(get=lambda _: source), generator).generate(
                CardRequest(source_id=source.id, count=1)
            )
    assert error.value.code == "cards_evidence_invalid" and len(calls) == 2


def test_graph_rejects_valid_global_evidence_missing_from_current_batch():
    source = source_for(chinese_text(30_000))

    def responder(task, payload, index):
        response = reply_for(task, payload, index)
        if index == 2:
            response["nodes"][0]["evidence_ids"] = ["e1"]
        return response

    with model_mock(responder=responder) as (generator, calls):
        with pytest.raises(DomainError) as error:
            build_model_graph(generator, [source], 1)
    assert error.value.code == "model_invalid_response" and len(calls) == 2


def test_graph_different_definitions_and_relation_explanations_are_preserved():
    source = source_for(chinese_text(30_000))

    def responder(task, payload, index):
        response = reply_for(task, payload, index)
        if index == 2:
            response["nodes"][0]["description"] = "限于本批语境的不同定义。"
        response["edges"][0]["explanation"] = f"第 {index} 批关系适用条件。"
        return response

    with model_mock(responder=responder) as (generator, calls):
        result = build_model_graph(generator, [source], 1)
    assert len(result.nodes) == 3
    assert len(result.edges) == len(calls)
    assert len({edge.id for edge in result.edges}) == len(calls)


def test_empty_batch_graph_is_valid_and_keeps_processing_later_evidence():
    source = source_for(chinese_text(30_000))

    def responder(task, payload, index):
        return {"nodes": [], "edges": []} if index == 1 else reply_for(task, payload, index)

    with model_mock(responder=responder) as (generator, calls):
        result = build_model_graph(generator, [source], 1)
    assert len(calls) > 1 and len(result.nodes) == 2
    assert (
        "".join(item["excerpt"] for call in calls for item in call["input"]["evidence"])
        == source.text
    )


def test_budget_check_uses_real_system_and_schema_without_network():
    with model_mock(num_ctx=100_000) as (generator, calls):
        payload = {"sections": [{"index": 0, "text": "甲"}]}
        generator.max_input_chars = len(json.dumps(payload, ensure_ascii=False)) + 10
        with pytest.raises(DomainError) as error:
            generator.check_budget(
                task="reading",
                instructions=READING_INSTRUCTIONS,
                payload=payload,
                response_model=GeneratedReading,
            )
    assert error.value.code == "model_input_too_large" and calls == []


def test_excess_batch_count_is_rejected_before_any_network_request():
    def check_budget(**kwargs):
        if len(kwargs["payload"]["items"]) > 1:
            raise DomainError("model_input_too_large", "每批只能处理一个片段", 413)

    called = []
    generator = SimpleNamespace(check_budget=check_budget, generate=lambda **_: called.append(True))
    with pytest.raises(DomainError) as error:
        batches = budget_batches(
            generator,
            list(range(65)),
            task="cards",
            instructions=CARDS_INSTRUCTIONS,
            payload_for=lambda batch: {"items": batch},
            response_model=GeneratedCards,
        )
        for batch in batches:
            generator.generate(payload=batch)
    assert error.value.code == "model_batch_limit" and error.value.status == 413
    assert called == []
