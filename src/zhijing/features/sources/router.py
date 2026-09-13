from typing import Literal

from fastapi import APIRouter, Depends, Query

from zhijing.dependencies import get_container
from zhijing.domain.models import Source, SourceGroup, SourceGroupPage, SourcePage
from zhijing.features.sources.schemas import (
    DeleteSourcesRequest,
    DeleteSourcesResult,
    ImportRequest,
    QuestionTitleRequest,
)
from zhijing.settings_ui import guard

router = APIRouter(prefix="/sources", tags=["资料库"])


@router.post("/import", response_model=list[Source])
def import_sources(body: ImportRequest, container=Depends(get_container)):
    return container.sources.import_items(body.items)


@router.get("", response_model=list[Source])
def list_sources(
    author_id: str | None = None,
    question_id: str | None = Query(None, max_length=30, pattern=r"^[0-9]*$"),
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container),
):
    return container.sources.list(author_id, offset, limit, question_id)


@router.get("/search", response_model=SourcePage)
def search_sources(
    q: str = Query(
        "", max_length=200, description="标题、作者名称、正文或主题的字面子串；空值返回全部资料"
    ),
    author_id: str | None = None,
    question_id: str | None = Query(None, max_length=30, pattern=r"^[0-9]*$"),
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container),
):
    return container.sources.search(author_id, q, offset, limit, question_id)


@router.get("/groups", response_model=SourceGroupPage)
def source_groups(
    by: Literal["author", "question"],
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container),
):
    return container.sources.groups(by, q, offset, limit)


@router.post("/delete", response_model=DeleteSourcesResult, dependencies=[Depends(guard)])
def delete_sources(body: DeleteSourcesRequest, container=Depends(get_container)):
    deleted = container.sources.delete(body.source_ids)
    return DeleteSourcesResult(deleted_ids=deleted, deleted_count=len(deleted))


@router.post("/question-title", response_model=SourceGroup, dependencies=[Depends(guard)])
def set_question_title(body: QuestionTitleRequest, container=Depends(get_container)):
    return container.sources.set_question_title(body.question_id, body.title)


@router.get("/{source_id}", response_model=Source)
def get_source(source_id: str, container=Depends(get_container)):
    return container.sources.require(source_id)
