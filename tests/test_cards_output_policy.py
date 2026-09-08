from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from zhijing.core.output_policy import (
    CARD_BACK_MAX,
    CARD_EVIDENCE_MAX,
    CARD_FRONT_MAX,
    zhihu_instructions,
)
from zhijing.features.cards.export import export_tsv
from zhijing.features.cards.generation import CARDS_INSTRUCTIONS, GeneratedCard
from zhijing.features.cards.schemas import CardRequest, ExportRequest
from zhijing.features.cards.service import CardService


def generated_card(**overrides):
    return {
        "front": "什么情况下应降低复习间隔？",
        "back": "如果回忆困难，应缩短复习间隔。",
        "evidence_excerpt": "如果回忆困难，应缩短复习间隔。",
        **overrides,
    }


def source_repository(text, title="复习建议"):
    source = SimpleNamespace(id="source-1", title=title, text=text)
    return SimpleNamespace(get=lambda _: source)


@pytest.mark.parametrize(
    ("field", "maximum"),
    [
        ("front", CARD_FRONT_MAX),
        ("back", CARD_BACK_MAX),
        ("evidence_excerpt", CARD_EVIDENCE_MAX),
    ],
)
def test_generated_card_limits_accept_boundary_and_reject_overflow(field, maximum):
    exact = generated_card(**{field: "字" * maximum})
    assert getattr(GeneratedCard.model_validate(exact), field) == exact[field]
    with pytest.raises(ValidationError):
        GeneratedCard.model_validate(generated_card(**{field: "字" * (maximum + 1)}))
    schema = GeneratedCard.model_json_schema()["properties"][field]
    assert schema["maxLength"] == maximum
    assert schema["description"]


@pytest.mark.parametrize(
    ("front", "back"),
    [
        ("条件是什么？", "条件是什么？"),
        (" Core   Concept\n", "core\tconcept"),
        ("Straße", "STRASSE"),
    ],
)
def test_generated_card_rejects_question_copied_into_answer(front, back):
    with pytest.raises(ValidationError, match="卡片问题与答案不能相同"):
        GeneratedCard.model_validate(generated_card(front=front, back=back))


def test_generated_card_keeps_distinct_answer_and_original_evidence():
    evidence = "如果回忆困难，\t应缩短复习间隔。\n下一次再根据表现调整。"
    card = GeneratedCard.model_validate(generated_card(evidence_excerpt=evidence))
    assert card.front != card.back
    assert card.evidence_excerpt == evidence
    assert zhihu_instructions("cards") in CARDS_INSTRUCTIONS


def test_offline_cards_bound_prompt_and_preserve_complete_original_sentences():
    short = "学习效果需要通过回忆表现来判断。"
    exact = "甲" * (CARD_BACK_MAX - 1) + "。"
    too_long = "乙" * CARD_BACK_MAX + "。"
    text = f"  \n{too_long}\n\t{short}  \n{exact}\n{short} "
    repository = source_repository(text, title="长标题" * 66)
    result = CardService(repository).generate(CardRequest(source_id="source-1", count=5))

    assert result.mode == "extractive"
    assert len(result.cards) == 2
    assert [card.back for card in result.cards] == [short, exact]
    for card in result.cards:
        assert len(card.front) <= CARD_FRONT_MAX
        assert len(card.back) <= CARD_BACK_MAX
        assert card.evidence_excerpt == card.back
        assert card.evidence_excerpt in text
        assert card.source_id == "source-1"
    assert "原文摘录" in result.notice
    assert f"已跳过 1 条超过 {CARD_BACK_MAX} 字符" in result.notice
    assert "未截断原文" in result.notice
    assert repository.get("source-1").text == text
    assert repository.get("source-1").title == "长标题" * 66


def test_offline_cards_report_all_overlong_material_without_truncating_it():
    text = "完整论述" * CARD_BACK_MAX
    result = CardService(source_repository(text)).generate(CardRequest(source_id="source-1"))
    assert result.cards == []
    assert "已跳过 1 条" in result.notice
    assert "原文摘录" in result.notice


def test_generated_limits_do_not_restrict_existing_card_exports():
    front = "问" * (CARD_FRONT_MAX + 1)
    back = "答" * (CARD_BACK_MAX + 1)
    request = ExportRequest.model_validate(
        {"cards": [{"front": front, "back": back, "source_id": "source-1"}]}
    )
    exported = export_tsv(request)
    assert front in exported
    assert back in exported
