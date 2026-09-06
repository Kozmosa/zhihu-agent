from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ShortText = Annotated[NonBlank, Field(max_length=200)]


def nonblank_original(value: str) -> str:
    if not value.strip():
        raise ValueError("Source text must contain non-whitespace characters")
    return value


RawText = Annotated[str, Field(min_length=1), AfterValidator(nonblank_original)]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDraft(Schema):
    title: ShortText
    author_id: ShortText
    author_name: ShortText
    text: Annotated[RawText, Field(max_length=100_000)]
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
