from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortText = Annotated[NonBlank, Field(max_length=200)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDraft(Schema):
    title: ShortText
    author_id: ShortText
    author_name: ShortText
    text: Annotated[NonBlank, Field(max_length=100_000)]
    url: HttpUrl | None = None
    topics: list[ShortText] = Field(default_factory=list, max_length=20)
    origin: Literal["manual", "zhihu", "demo"] = "manual"


class Source(SourceDraft):
    id: str
    created_at: str


class Citation(Schema):
    source_id: str
    title: str
    author_id: str
    url: str | None
    chunk_index: int
    excerpt: str
    score: float


class Generation(Schema):
    text: str
    mode: Literal["extractive", "ollama"]
