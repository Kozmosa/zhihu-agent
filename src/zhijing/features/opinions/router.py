from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.features.opinions.schemas import OpinionMap, OpinionRequest

router = APIRouter(prefix="/opinion-map", tags=["知识地图：回答观点分类"])


@router.post("", response_model=OpinionMap)
def classify(body: OpinionRequest, container=Depends(get_container)):
    return container.opinions.build(body)
