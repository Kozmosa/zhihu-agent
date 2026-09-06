from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.domain.models import Citation
from zhijing.features.retrieval.schemas import SearchRequest

router = APIRouter(prefix="/retrieval", tags=["检索与引用"])


@router.post("/search", response_model=list[Citation])
def search(body: SearchRequest, container=Depends(get_container)):
    return container.retriever.search(body.query, body.author_id, body.limit)
