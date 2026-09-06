from pydantic import Field

from zhijing.domain.models import Schema, SourceDraft


class ImportRequest(Schema):
    items: list[SourceDraft] = Field(min_length=1, max_length=20)
