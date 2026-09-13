"""A narrow authenticated userscript bridge; ordinary workspace guards stay intact."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from zhijing.core.errors import DomainError
from zhijing.features.zhihu.companion import BrowserCapture
from zhijing.settings_ui import guard

router = APIRouter(prefix="/zhihu/companion", tags=["知乎伴侣"])


def inbox(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.runtime.companion_inbox


@router.post("/pair", dependencies=[Depends(guard)])
def pair(store=Depends(inbox)):
    return {"token": store.pair()}


@router.get("/status", dependencies=[Depends(guard)])
def status(store=Depends(inbox)):
    with store.lock:
        return {"paired": bool(store.token_hash), "pending_count": len(store.batches)}


@router.get("/inbox", dependencies=[Depends(guard)])
def list_inbox(store=Depends(inbox)):
    return {"items": store.summaries()}


@router.get("/inbox/{batch_id}", dependencies=[Depends(guard)])
def get_capture(batch_id: str, store=Depends(inbox)):
    return store.get(batch_id)


@router.post("/inbox/{batch_id}/dismiss", dependencies=[Depends(guard)])
def dismiss(batch_id: str, store=Depends(inbox)):
    return {"removed": store.dismiss(batch_id)}


@router.post("/receive")
async def receive(request: Request, store=Depends(inbox)):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise DomainError("local_only", "采集接收接口仅允许本机访问。", 403)
    store.authenticate(request.headers.get("x-zhijing-companion", ""))
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("invalid_browser_capture", "请使用 JSON 发送采集内容。", 415)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 12_000_000:
            raise DomainError("browser_capture_too_large", "本批内容过多，请分批发送。", 413)
    try:
        capture = BrowserCapture.model_validate_json(bytes(body))
    except (ValidationError, ValueError):
        raise DomainError(
            "invalid_browser_capture", "采集内容格式不完整，请更新脚本后重新采集。", 422
        ) from None
    return await run_in_threadpool(store.receive, capture)
