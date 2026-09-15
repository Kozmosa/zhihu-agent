from pydantic import Field

from zhijing.domain.models import Schema, ShortText, SourceDraft


class ImportRequest(Schema):
    items: list[SourceDraft] = Field(min_length=1, max_length=20)


class QuestionTitleRequest(Schema):
    question_id: str = Field(pattern=r"^[0-9]{1,30}$")
    title: ShortText


class DeleteSourcesRequest(Schema):
    source_ids: list[ShortText] = Field(min_length=1, max_length=100)


class DeleteSourcesResult(Schema):
    deleted_ids: list[str]
    deleted_count: int
