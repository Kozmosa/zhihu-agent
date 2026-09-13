"""Local, user-initiated website previews with session-only login state."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, SecretStr, ValidationError

from zhijing.core.errors import DomainError
from zhijing.domain.models import Schema
from zhijing.features.zhihu.schemas import ZhihuStatus
from zhijing.features.zhihu.web_schemas import ZhihuWebPreviewRequest, ZhihuWebPreviewResult
from zhijing.features.zhihu.web_service import ZhihuWebService
from zhijing.settings_ui import guard

router = APIRouter(prefix="/zhihu/web", tags=["知乎网页批量导入"], dependencies=[Depends(guard)])


class WebConfiguration(Schema):
    cookie: SecretStr = Field(max_length=16384)


@router.get("/status", response_model=ZhihuStatus)
def status(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    runtime = request.app.state.runtime
    with runtime.lock:
        return ZhihuStatus(configured=bool(runtime.zhihu_web_cookie))


@router.post("/config", response_model=ZhihuStatus)
async def configure(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("invalid_web_config", "请使用 JSON 配置请求。", 415)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 20000:
            raise DomainError("invalid_web_config", "网页登录信息过大。", 413)
    try:
        config = WebConfiguration.model_validate_json(bytes(content))
        cookie = config.cookie.get_secret_value().strip()
        if cookie and (
            not cookie.isascii()
            or any(ord(character) < 32 or ord(character) == 127 for character in cookie)
            or any(
                "=" not in part or not part.split("=", 1)[0].strip()
                for part in cookie.split(";")
                if part.strip()
            )
        ):
            raise ValueError("invalid cookie header")
    except (ValidationError, ValueError):
        # Never let FastAPI include credential input in validation errors.
        raise DomainError(
            "invalid_web_config", "网页登录信息格式无效，请重新输入 Cookie。", 422
        ) from None
    runtime = request.app.state.runtime
    with runtime.lock:
        runtime.zhihu_web_cookie = cookie
    return ZhihuStatus(configured=bool(cookie))


@router.post("/preview", response_model=ZhihuWebPreviewResult)
def preview(body: ZhihuWebPreviewRequest, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    runtime = request.app.state.runtime
    if not runtime.zhihu_web_lock.acquire(blocking=False):
        raise DomainError("zhihu_web_busy", "已有网页读取任务，请等它完成后再试。", 409)
    try:
        with runtime.lock:
            cookie = runtime.zhihu_web_cookie
        return ZhihuWebService().preview(body, cookie=cookie)
    finally:
        runtime.zhihu_web_lock.release()
