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
    citation_notice: str = "引用为实际检索资料；模型文字与引用的对应关系仍需人工核对。"
