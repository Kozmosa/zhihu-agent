from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import NonBlank, Schema, ShortText


class CardRequest(Schema):
    source_id: ShortText
    count: int = Field(5, ge=1, le=30)


class Card(Schema):
    front: Annotated[NonBlank, Field(max_length=2000)]
    back: Annotated[NonBlank, Field(max_length=5000)]
    source_id: ShortText
    evidence_excerpt: Annotated[NonBlank, Field(max_length=5000)] | None = None


class CardSet(Schema):
    cards: list[Card]
    mode: Literal["extractive", "ollama"] = "extractive"
    notice: str = "自动摘录草稿，请检查问题质量与原文含义后再导入复习。"


class ExportRequest(Schema):
    deck_name: ShortText = "知境::阅读卡片"
    cards: list[Card] = Field(min_length=1, max_length=100)
