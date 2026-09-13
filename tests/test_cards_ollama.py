from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from zhijing.core.errors import DomainError
from zhijing.features.cards.export import export_tsv
from zhijing.features.cards.generation import GeneratedCards
from zhijing.features.cards.schemas import CardRequest, ExportRequest
from zhijing.features.cards.service import CardService


class CardsModel:
    def __init__(self, cards=None, failure=None):
        self.cards = cards
        self.failure = failure
        self.payload = None

    def generate(self, *, task, instructions, payload, response_model):
        assert task == "cards"
        assert instructions
        assert response_model is GeneratedCards
        assert "source_id" not in payload
        self.payload = payload
        if self.failure:
            raise self.failure
        cards = self.cards if self.cards is not None else [example_card()]
        return response_model.model_validate({"cards": cards})


def example_card(**overrides):
    return {
        "front": "主动回忆如何帮助发现理解缺口？",
        "back": "合上书提取所学，再将回忆内容与原文对照。",
        "evidence_excerpt": "主动回忆是合上书主动提取所学内容。",
        **overrides,
    }


@pytest.fixture
def repository():
    source = SimpleNamespace(
        id="source-1",
        title="学习方法",
        text="主动回忆是合上书主动提取所学内容。\n将回忆内容与原文对照，可以发现理解缺口。",
    )
    return SimpleNamespace(get=lambda source_id: source)


def test_model_generates_concept_cards_with_verified_original_evidence(repository):
    generator = CardsModel()
    result = CardService(repository, generator).generate(CardRequest(source_id="source-1"))
    assert result.mode == "ollama"
    assert len(result.cards) == 1
    assert result.cards[0].front == example_card()["front"]
    assert result.cards[0].source_id == "source-1"
    assert result.cards[0].evidence_excerpt in repository.get("source-1").text
    assert generator.payload["text"] == repository.get("source-1").text
    assert "模型生成" in result.notice
    # New optional evidence metadata must not break the existing three-column export API.
    request = ExportRequest.model_validate({"cards": result.model_dump()["cards"]})
    tsv = export_tsv(request)
    assert "#columns:Front\tBack\tSource" in tsv
    assert "source-1" in tsv


@pytest.mark.parametrize(
    "evidence",
    ["主动回忆保证永远不会遗忘。", "主动回忆是合上书…发现理解缺口。"],
)
def test_cards_reject_fabricated_or_stitched_evidence(repository, evidence):
    generator = CardsModel([example_card(evidence_excerpt=evidence)])
    with pytest.raises(DomainError) as error:
        CardService(repository, generator).generate(CardRequest(source_id="source-1"))
    assert error.value.code == "cards_evidence_invalid"
    assert error.value.status == 502


@pytest.mark.parametrize("count", [1, 2])
def test_cards_limit_excess_count_and_merge_duplicate_questions(repository, count):
    generator = CardsModel([example_card(), example_card()])
    result = CardService(repository, generator).generate(
        CardRequest(source_id="source-1", count=count)
    )
    assert len(result.cards) == 1
    assert result.cards[0].evidence_excerpt in repository.get("source-1").text
    assert "已跳过 1 张" in result.notice


def test_insufficient_material_may_produce_zero_cards(repository):
    result = CardService(repository, CardsModel([])).generate(CardRequest(source_id="source-1"))
    assert result.mode == "ollama"
    assert result.cards == []


def test_cards_source_identifiers_cannot_be_model_generated():
    with pytest.raises(ValidationError):
        GeneratedCards.model_validate({"cards": [example_card(source_id="invented-source")]})


def test_cards_offline_default_retains_template_and_source(repository):
    result = CardService(repository).generate(CardRequest(source_id="source-1", count=1))
    assert result.mode == "extractive"
    assert result.cards[0].back in repository.get("source-1").text
    assert result.cards[0].source_id == "source-1"


def test_cards_model_errors_propagate_without_template_fallback(repository):
    failure = DomainError("model_unavailable", "模型不可用", 502)
    with pytest.raises(DomainError) as error:
        CardService(repository, CardsModel(failure=failure)).generate(CardRequest(source_id="s"))
    assert error.value is failure


def test_cards_missing_source_does_not_call_model():
    generator = CardsModel()
    with pytest.raises(DomainError) as error:
        CardService(SimpleNamespace(get=lambda _: None), generator).generate(
            CardRequest(source_id="missing")
        )
    assert error.value.code == "source_not_found"
    assert generator.payload is None
