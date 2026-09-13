import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from zhijing.core.errors import DomainError
from zhijing.core.output_policy import (
    POLICY_VERSION,
    READING_HEADING_MAX,
    READING_POINT_MAX,
    READING_POINTS_MAX,
    READING_QUESTION_MAX,
    READING_SUMMARY_MAX,
)
from zhijing.features.reader.generation import GeneratedReading
from zhijing.features.reader.schemas import ReadingRequest
from zhijing.features.reader.service import ReaderService
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator


def output():
    return {
        "summary": "作者观察到提问意愿变化，未测量长期成绩。",
        "sections": [
            {
                "index": 0,
                "heading": "观察与限制",
                "key_points": ["观察限于两周课程，且没有对照组。"],
                "guiding_question": "哪些信息不足以支持因果结论？",
            }
        ],
    }


@pytest.mark.parametrize(
    "field,limit",
    [
        ("summary", READING_SUMMARY_MAX),
        ("heading", READING_HEADING_MAX),
        ("key_points", READING_POINT_MAX),
        ("guiding_question", READING_QUESTION_MAX),
    ],
)
def test_reading_generated_field_boundaries(field, limit):
    valid = output()
    for size in (limit, limit + 1):
        candidate = copy.deepcopy(valid)
        if field == "summary":
            candidate[field] = "字" * size
        elif field == "key_points":
            candidate["sections"][0][field] = ["字" * size]
        else:
            candidate["sections"][0][field] = "字" * size
        if size == limit:
            GeneratedReading.model_validate(candidate)
        else:
            with pytest.raises(ValidationError):
                GeneratedReading.model_validate(candidate)


def test_reading_points_are_limited_and_must_be_distinct():
    candidate = output()
    candidate["sections"][0]["key_points"] = [
        f"观点 {index}" for index in range(READING_POINTS_MAX)
    ]
    GeneratedReading.model_validate(candidate)
    candidate["sections"][0]["key_points"].append("另一个观点")
    with pytest.raises(ValidationError):
        GeneratedReading.model_validate(candidate)
    candidate["sections"][0]["key_points"] = ["A point", " a  POINT "]
    with pytest.raises(ValidationError):
        GeneratedReading.model_validate(candidate)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("overlong", [False, True])
def test_both_transports_enforce_style_schema_without_changing_source(provider, overlong):
    source_text = "  谢邀，这是作者原文中的开场。\n观察仅限两周课程，不能说明长期成绩。  "
    captured = []

    def respond(request):
        body = json.loads(request.content)
        instructions = body["system"] if provider == "ollama" else body["messages"][0]["content"]
        prompt = body["prompt"] if provider == "ollama" else body["messages"][1]["content"]
        captured.append((instructions, json.loads(prompt)))
        content = output()
        if overlong:
            content["summary"] = "字" * (READING_SUMMARY_MAX + 1)
        generated = json.dumps(content, ensure_ascii=False)
        response = (
            {"response": generated, "done": True}
            if provider == "ollama"
            else {"choices": [{"message": {"content": generated}, "finish_reason": "stop"}]}
        )
        return httpx.Response(200, json=response)

    with httpx.Client(
        transport=httpx.MockTransport(respond), base_url="https://model.test/"
    ) as client:
        model_type = OllamaGenerator if provider == "ollama" else OpenAICompatibleGenerator
        generator = model_type(client, "test-model")
        service = ReaderService(None, generator)
        if overlong:
            with pytest.raises(DomainError) as error:
                service.analyze(ReadingRequest(text=source_text))
            assert error.value.code == "model_invalid_response" and error.value.status == 502
        else:
            result = service.analyze(ReadingRequest(text=source_text))
            assert result.mode == provider
            assert "".join(section.text for section in result.sections) == source_text
    assert len(captured) == 1
    assert POLICY_VERSION in captured[0][0]
    assert captured[0][1]["input"]["sections"][0]["text"] == source_text
