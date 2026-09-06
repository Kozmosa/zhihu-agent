from fastapi import APIRouter, Depends

from zhijing.dependencies import get_container
from zhijing.features.reader.schemas import ReadingRequest, ReadingResult

router = APIRouter(prefix="/reading", tags=["长文拆解"])


@router.post("/analyze", response_model=ReadingResult)
def analyze(body: ReadingRequest, container=Depends(get_container)):
    return container.reader.analyze(body)
