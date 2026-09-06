from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import Citation, NonBlank, Schema, ShortText


class AuthorQuestion(Schema):
    author_id: ShortText
    question: Annotated[NonBlank, Field(max_length=2000)]
    primary_source_id: ShortText | None = None
    top_k: int = Field(5, ge=1, le=10)


class AuthorAnswer(Schema):
    answer: str
    mode: Literal["extractive", "ollama"]
    citations: list[Citation]
    identity_notice: str = "基于历史资料的阅读助手，不代表原答主本人或其当前观点。"
    citation_notice: str = "引用列表为提供给生成器的真实资料，编号从1开始；未标记的片段不代表被采用，语义支持关系仍需核对。"
