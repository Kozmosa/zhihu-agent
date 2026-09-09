from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse

from zhijing.dependencies import get_container
from zhijing.features.runs.schemas import RunPage, RunRecord, RunRequest, RunStatus

router = APIRouter(prefix="/runs", tags=["持久化工作流"])


@router.post("", response_model=RunRecord)
def create(
    body: RunRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    ],
    container=Depends(get_container),
):
    return container.runs.create(body, idempotency_key)


@router.get("", response_model=RunPage)
def list_runs(
    offset: int = Query(0, ge=0, le=2**63 - 1),
    limit: int = Query(20, ge=1, le=100),
    source_id: str | None = Query(None, min_length=1, max_length=200),
    status: RunStatus | None = None,
    container=Depends(get_container),
):
    return container.runs.list(offset, limit, source_id, status)


@router.get("/{run_id}", response_model=RunRecord)
def get(run_id: str, container=Depends(get_container)):
    return container.runs.get(run_id)


@router.post("/{run_id}/execute", response_model=RunRecord)
def execute(run_id: str, container=Depends(get_container)):
    return container.runs.execute(run_id)


@router.post("/{run_id}/retry", response_model=RunRecord)
def retry(run_id: str, container=Depends(get_container)):
    return container.runs.retry(run_id)


@router.post("/{run_id}/cancel", response_model=RunRecord)
def cancel(run_id: str, container=Depends(get_container)):
    return container.runs.cancel(run_id)


@router.get("/{run_id}/transcript", response_class=JSONResponse)
def transcript(run_id: str, container=Depends(get_container)):
    events = container.transcript.list(run_id) if container.transcript else []
    return JSONResponse(
        content=events,
        headers={"Content-Disposition": f'attachment; filename="transcript-{run_id}.json"'},
    )
