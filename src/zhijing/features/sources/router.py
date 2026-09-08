from fastapi import APIRouter, Depends, Query

from zhijing.dependencies import get_container
from zhijing.domain.models import Source, SourcePage
from zhijing.features.sources.schemas import ImportRequest

router = APIRouter(prefix="/sources", tags=["资料库"])


@router.post("/import", response_model=list[Source])
def import_sources(body: ImportRequest, container=Depends(get_container)):
    return container.sources.import_items(body.items)


@router.get("", response_model=list[Source])
def list_sources(
    author_id: str | None = None,
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container),
):
    return container.sources.list(author_id, offset, limit)


@router.get("/search", response_model=SourcePage)
def search_sources(
    q: str = Query(
        "", max_length=200, description="标题、作者名称、正文或主题的字面子串；空值返回全部资料"
    ),
    author_id: str | None = None,
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    container=Depends(get_container),
):
    return container.sources.search(author_id, q, offset, limit)


@router.get("/{source_id}", response_model=Source)
def get_source(source_id: str, container=Depends(get_container)):
    return container.sources.require(source_id)
