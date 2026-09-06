from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.features.facts.schemas import FactRequest, FactResult

router = APIRouter(prefix="/facts", tags=["事实审查"])


@router.post("/review", response_model=FactResult)
def review(body: FactRequest, container=Depends(get_container)):
    return container.facts.review(body)
