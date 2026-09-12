from typing import Annotated, Literal

from pydantic import Field, SecretStr, StringConstraints

from zhijing.domain.models import Schema, SourceDraft


class ZhihuConfiguration(Schema):
    access_secret: SecretStr = Field(max_length=4096)


class ZhihuStatus(Schema):
    configured: bool


class ZhihuSearchRequest(Schema):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    count: int = Field(default=3, strict=True, ge=1, le=10)


class ZhihuSearchResult(Schema):
    items: list[SourceDraft]
    has_more: Literal[False] = False
    empty_reason: str = ""
    skipped_count: int = 0
