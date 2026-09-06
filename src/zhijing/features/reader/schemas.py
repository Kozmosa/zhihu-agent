from typing import Annotated, Literal

from pydantic import Field, model_validator

from zhijing.domain.models import RawText, Schema, ShortText


class ReadingRequest(Schema):
    source_id: ShortText | None = None
    text: Annotated[RawText, Field(max_length=100_000)] | None = None
    chunk_size: int = Field(600, ge=100, le=2000)

    @model_validator(mode="after")
    def exactly_one_input(self):
        if (self.source_id is None) == (self.text is None):
            raise ValueError("source_id 和 text 必须且只能提供一个")
        return self


class Section(Schema):
    index: int
    heading: str
    text: str
    key_points: list[str]
    guiding_question: str


class ReadingResult(Schema):
    source_id: str | None
    mode: Literal["extractive", "ollama"] = "extractive"
    summary: str
    sections: list[Section]
    notice: str = "当前采用分句与首句摘录，未进行语义推理；导读问题为模板。"
