from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from zhijing.domain.models import Citation, NonBlank, Schema
from zhijing.features.knowledge.schemas import SourceExtentCounts

SourceId = Annotated[NonBlank, Field(max_length=100)]


class OpinionRequest(Schema):
    question: Annotated[NonBlank, Field(max_length=2048)]
    source_ids: list[SourceId] | None = Field(default=None, min_length=1, max_length=50)
    limit: int = Field(default=20, ge=1, le=50, strict=True)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if self.source_ids and len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("同一篇回答不能重复选择。")
        return self


class AnswerReference(Schema):
    source_id: str
    title: str
    author_id: str
    author_name: str
    author_identity_known: bool
    url: str | None
    content_extent: Literal["fulltext", "excerpt", "unknown"]
    analyzed_chars: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    partial_analysis: bool


class OpinionPosition(AnswerReference):
    stance: str
    summary: str
    evidence: list[Citation]


class OpinionGroup(Schema):
    id: str
    label: str
    summary: str
    answer_count: int = Field(ge=1)
    known_author_count: int = Field(ge=0)
    positions: list[OpinionPosition]


class UnclassifiedAnswer(AnswerReference):
    category: Literal[
        "off_topic", "insufficient_evidence", "not_answer", "duplicate_answer_version"
    ]
    reason: str
    duplicate_of_source_id: str | None = None


class OpinionMap(Schema):
    question: str
    question_url: str | None
    mode: Literal["openai", "ollama"]
    selection_mode: Literal["explicit_sources", "question_url", "local_search"]
    groups: list[OpinionGroup]
    unclassified: list[UnclassifiedAnswer]
    total_sources: int = Field(ge=0)
    included_sources: int = Field(ge=0)
    classified_sources: int = Field(ge=0)
    known_author_count: int = Field(ge=0)
    unknown_author_sources: int = Field(ge=0)
    partial_sources: int = Field(ge=0)
    omitted_source_ids: list[str]
    content_extent_counts: SourceExtentCounts
    truncated: bool
    analysis_notice: str
