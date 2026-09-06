from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import Citation, NonBlank, Schema, ShortText


class FactRequest(Schema):
    claims: list[Annotated[NonBlank, Field(max_length=2000)]] = Field(min_length=1, max_length=20)
    author_id: ShortText | None = None
    exclude_source_ids: list[ShortText] = Field(default_factory=list, max_length=20)


class ClaimReview(Schema):
    claim: str
    status: Literal["mentioned_in_corpus", "related_evidence", "insufficient_evidence"]
    explanation: str
    evidence: list[Citation]


class FactResult(Schema):
    reviews: list[ClaimReview]
    scope: str = "仅审查已导入语料。文本出现、相似度和作者观点均不能证明客观事实。"
