from typing import Annotated

from pydantic import Field

from zhijing.domain.models import NonBlank, Schema, ShortText


class SearchRequest(Schema):
    query: Annotated[NonBlank, Field(max_length=2000)]
    author_id: ShortText | None = None
    limit: int = Field(5, ge=1, le=20)
