from fastapi import APIRouter, Depends, Response

from zhijing.dependencies import get_container
from zhijing.features.cards.export import export_apkg, export_tsv
from zhijing.features.cards.schemas import CardRequest, CardSet, ExportRequest

router = APIRouter(prefix="/cards", tags=["记忆卡片"])


@router.post("/generate", response_model=CardSet)
def generate(body: CardRequest, container=Depends(get_container)):
    return container.cards.generate(body)


@router.post("/export/tsv")
def tsv(body: ExportRequest):
    return Response(
        export_tsv(body),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": 'attachment; filename="zhijing-cards.tsv"'},
    )


@router.post("/export/apkg")
def apkg(body: ExportRequest, container=Depends(get_container)):
    return Response(
        export_apkg(body, container.export_dir),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="zhijing-cards.apkg"'},
    )
