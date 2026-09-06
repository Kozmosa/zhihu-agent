from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.features.companion.schemas import CompanionRequest, CompanionResult

router = APIRouter(prefix="/companion", tags=["知境统一入口"])


@router.post("/run", response_model=CompanionResult)
def run(body: CompanionRequest, container=Depends(get_container)):
    return container.companion.run(body)
