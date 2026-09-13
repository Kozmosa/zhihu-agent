from fastapi import APIRouter, Depends, Query

from zhijing.dependencies import get_container
from zhijing.features.knowledge.schemas import KnowledgeGraph

router = APIRouter(prefix="/knowledge-map", tags=["知识地图"])


@router.get("", response_model=KnowledgeGraph)
def graph(
    author_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    primary_source_id: str | None = None,
    container=Depends(get_container),
):
    return container.knowledge.build(author_id, limit, primary_source_id)
