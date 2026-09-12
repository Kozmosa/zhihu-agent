"""Preview contracts for a bounded, user-requested Zhihu web import."""

from typing import Literal

from pydantic import Field

from zhijing.domain.models import Schema, SourceDraft


class ZhihuWebPreviewRequest(Schema):
    url: str = Field(min_length=1, max_length=2048)
    mode: Literal["question", "author"]
    min_votes: int = Field(100, ge=0, le=1_000_000_000)
    max_items: int = Field(20, ge=1, le=100)


class ZhihuWebItem(Schema):
    draft: SourceDraft
    answer_id: str
    question_id: str
    voteup_count: int | None


class ZhihuWebPreviewResult(Schema):
    items: list[ZhihuWebItem] = Field(default_factory=list)
    scanned_count: int = 0
    skipped_count: int = 0
    pages_fetched: int = 0
    has_more: bool = False
    stop_reason: str
    warning: str
    target_label: str
