import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from zhijing.core.errors import DomainError
from zhijing.core.output_policy import (
    FACT_CONDITION_MAX,
    FACT_CONDITIONS_MAX,
    FACT_EXPLANATION_MAX,
    FACT_RATIONALE_MAX,
    zhihu_instructions,
)
from zhijing.domain.models import Source
from zhijing.features.facts.model_schemas import GeneratedReview
from zhijing.features.facts.schemas import FactRequest
from zhijing.features.facts.service import FactService
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator


def decision():
    return {
        "verdict": "supported",
        "explanation": "The supplied text supports this statement; it is not independent proof.",
        "assessments": [
            {
                "evidence_id": "e1",
                "relation": "supports",
                "rationale": "The source states this explicitly, within its original context.",
            }
        ],
        "conditions": ["Only the supplied source has been examined."],
    }


def set_text(response, field, value):
    if field == "rationale":
        response["assessments"][0][field] = value
    elif field == "condition":
        response["conditions"] = [value]
    else:
        response[field] = value


@pytest.mark.parametrize(
    "field,limit",
    [
        ("explanation", FACT_EXPLANATION_MAX),
        ("rationale", FACT_RATIONALE_MAX),
        ("condition", FACT_CONDITION_MAX),
    ],
)
def test_generated_fact_text_accepts_boundary_and_rejects_overflow(field, limit):
    response = decision()
    set_text(response, field, "界" * limit)
    assert GeneratedReview.model_validate(response).model_dump() == response
    set_text(response, field, "界" * (limit + 1))
    with pytest.raises(ValidationError) as error:
        GeneratedReview.model_validate(response)
    assert any(item["type"] == "string_too_long" for item in error.value.errors())


def test_fact_conditions_accept_boundary_and_reject_extra_item():
    response = decision()
    response["conditions"] = [f"证据限定条件 {index}" for index in range(FACT_CONDITIONS_MAX)]
    assert GeneratedReview.model_validate(response).conditions == response["conditions"]
    response["conditions"].append("额外的适用条件")
    with pytest.raises(ValidationError) as error:
        GeneratedReview.model_validate(response)
    assert error.value.errors()[0]["loc"] == ("conditions",)
    assert error.value.errors()[0]["type"] == "too_long"


@pytest.fixture
def source():
    return Source(
        id="source-original",
        title="原文中的讽刺表达",
        author_id="author-original",
        author_name="原作者",
        text="“谢邀，人在美国，刚下飞机”是讽刺；“懂的都懂”只是口头禅。\n不能把段子当作事实证据。",
        created_at="2026-09-08T00:00:00Z",
    )


def fact_service(source, generator):
    repository = SimpleNamespace(list=lambda _author_id: [source] if source else [])
    retriever = SimpleNamespace(search=lambda *_args: [])
    return FactService(repository, retriever, generator)


@contextmanager
def mocked_model(generator_type, response):
    calls = []

    def handle(request):
        body = json.loads(request.content)
        if generator_type is OllamaGenerator:
            calls.append({"instructions": body["system"], **json.loads(body["prompt"])})
            envelope = {"response": json.dumps(response), "done": True}
        else:
            calls.append(
                {
                    "instructions": body["messages"][0]["content"],
                    **json.loads(body["messages"][1]["content"]),
                }
            )
            envelope = {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}]
            }
        return httpx.Response(200, json=envelope)

    with httpx.Client(
        base_url="https://facts-model.invalid", transport=httpx.MockTransport(handle)
    ) as client:
        yield generator_type(client, "facts-policy-fixture"), calls


@pytest.mark.parametrize(
    "generator_type", [OllamaGenerator, OpenAICompatibleGenerator], ids=["ollama", "openai"]
)
def test_fact_policy_reaches_each_provider_without_cleaning_claim_or_citations(
    source, generator_type
):
    response = decision()
    response["assessments"][0]["rationale"] = "原文提到“谢邀”和“懂的都懂”，但未把口头禅作为证明。"
    with mocked_model(generator_type, response) as (generator, calls):
        result = fact_service(source, generator).review(FactRequest(claims=[source.text]))
    review = result.reviews[0]
    assert result.mode == generator_type.mode
    assert review.claim == source.text
    assert review.explanation == response["explanation"]
    assert review.evidence[0].excerpt == source.text
    assert review.evidence_analysis[0].citation == review.evidence[0]
    assert review.evidence_analysis[0].rationale == response["assessments"][0]["rationale"]
    assert review.conditions == response["conditions"]
    assert len(calls) == 1
    assert zhihu_instructions("facts") in calls[0]["instructions"]
    assert calls[0]["input"]["claim"] == source.text
    assert calls[0]["input"]["evidence"][0]["excerpt"] == source.text


@pytest.mark.parametrize(
    "generator_type", [OllamaGenerator, OpenAICompatibleGenerator], ids=["ollama", "openai"]
)
@pytest.mark.parametrize("field", ["explanation", "rationale", "condition", "conditions"])
def test_oversized_fact_output_is_an_explicit_model_error(source, generator_type, field):
    response = decision()
    if field == "conditions":
        response[field] = [f"条件 {index}" for index in range(FACT_CONDITIONS_MAX + 1)]
    else:
        limit = {
            "explanation": FACT_EXPLANATION_MAX,
            "rationale": FACT_RATIONALE_MAX,
            "condition": FACT_CONDITION_MAX,
        }[field]
        set_text(response, field, "界" * (limit + 1))
    with mocked_model(generator_type, response) as (generator, calls):
        with pytest.raises(DomainError) as error:
            fact_service(source, generator).review(FactRequest(claims=[source.text]))
    assert error.value.code == "model_invalid_response"
    assert error.value.status == 502
    assert len(calls) == 1


@pytest.mark.parametrize("code", ["model_timeout", "model_unavailable"])
def test_fact_provider_failure_is_not_replaced_with_extractive_success(source, code):
    failure = DomainError(code, "模型服务调用失败。", 502)

    def fail(**_kwargs):
        raise failure

    with pytest.raises(DomainError) as error:
        fact_service(source, SimpleNamespace(generate=fail)).review(
            FactRequest(claims=[source.text])
        )
    assert error.value is failure


def test_fact_without_evidence_stays_insufficient_and_skips_model():
    def unexpected_generation(**_kwargs):
        raise AssertionError("No evidence must not reach the model")

    result = fact_service(None, SimpleNamespace(generate=unexpected_generation)).review(
        FactRequest(claims=["未找到证据不能说明这是假的。"])
    )
    review = result.reviews[0]
    assert result.mode == "extractive"
    assert review.status == "insufficient_evidence"
    assert review.evidence == review.evidence_analysis == []
    assert "不能据此断言该主张为假" in review.explanation
