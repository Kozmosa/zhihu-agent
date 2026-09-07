from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from zhijing.core.errors import DomainError
from zhijing.features.reader.generation import GeneratedReading
from zhijing.features.reader.schemas import ReadingRequest
from zhijing.features.reader.service import ReaderService


class ReadingModel:
    def __init__(self, indices=None, failure=None):
        self.indices = indices
        self.failure = failure
        self.payload = None

    def generate(self, *, task, instructions, payload, response_model):
        assert task == "reading"
        assert instructions
        assert response_model is GeneratedReading
        self.payload = payload
        if self.failure:
            raise self.failure
        indices = self.indices
        if indices is None:
            indices = [section["index"] for section in reversed(payload["sections"])]
        return response_model.model_validate(
            {
                "summary": "主动回忆通过主动提取检查理解。",
                "sections": [
                    {
                        "index": index,
                        "heading": f"概念与应用 {index}",
                        "key_points": ["用回忆结果发现理解中的缺口。"],
                        "guiding_question": "如何发现没有理解的内容？",
                    }
                    for index in indices
                ],
            }
        )


@pytest.fixture
def reading_input():
    text = "主动回忆是合上书主动提取所学内容。\n\n" * 20 + "最后核对遗漏。"
    return ReadingRequest(text=text, chunk_size=100)


def test_reading_model_enriches_without_rewriting_or_reordering_original(reading_input):
    generator = ReadingModel()
    result = ReaderService(None, generator).analyze(reading_input)
    assert result.mode == "ollama"
    assert result.source_id is None
    assert result.summary == "主动回忆通过主动提取检查理解。"
    assert "".join(section.text for section in result.sections) == reading_input.text
    assert [section.index for section in result.sections] == list(range(len(result.sections)))
    assert all(section.heading.startswith("概念与应用") for section in result.sections)
    assert (
        "".join(section["text"] for section in generator.payload["sections"]) == reading_input.text
    )
    assert "模型生成" in result.notice


@pytest.mark.parametrize("indices", [[0], [0, 0], [100]])
def test_reading_rejects_missing_duplicate_or_invented_indices(reading_input, indices):
    with pytest.raises(DomainError) as error:
        ReaderService(None, ReadingModel(indices)).analyze(reading_input)
    assert error.value.code == "model_invalid_response"
    assert error.value.status == 502


def test_reading_uses_repository_original_and_preserves_source_id(reading_input):
    repository = SimpleNamespace(get=lambda source_id: SimpleNamespace(text=reading_input.text))
    result = ReaderService(repository, ReadingModel()).analyze(ReadingRequest(source_id="source-1"))
    assert result.source_id == "source-1"
    assert "".join(section.text for section in result.sections) == reading_input.text


def test_reading_offline_mode_still_preserves_original(reading_input):
    result = ReaderService(None).analyze(reading_input)
    assert result.mode == "extractive"
    assert "".join(section.text for section in result.sections) == reading_input.text


def test_reading_model_failures_are_not_silently_downgraded(reading_input):
    failure = DomainError("model_context_too_large", "输入超限", 413)
    with pytest.raises(DomainError) as error:
        ReaderService(None, ReadingModel(failure=failure)).analyze(reading_input)
    assert error.value is failure


def test_reading_schema_rejects_rewritten_text_and_noninteger_indices():
    section = {"index": 0, "heading": "标题", "key_points": ["要点"], "guiding_question": "问题"}
    for change in [{"text": "模型改写的原文"}, {"index": "0"}]:
        with pytest.raises(ValidationError):
            GeneratedReading.model_validate(
                {"summary": "摘要", "sections": [{**section, **change}]}
            )


def test_reading_missing_source_does_not_call_model():
    generator = ReadingModel()
    with pytest.raises(DomainError) as error:
        ReaderService(SimpleNamespace(get=lambda _: None), generator).analyze(
            ReadingRequest(source_id="missing")
        )
    assert error.value.code == "source_not_found"
    assert generator.payload is None
