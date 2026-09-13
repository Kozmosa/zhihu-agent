"""Local guarded search and transient access-secret configuration."""

from dataclasses import replace

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from zhijing.container import build_container
from zhijing.core.errors import DomainError
from zhijing.dependencies import get_container
from zhijing.features.zhihu.schemas import (
    ZhihuConfiguration,
    ZhihuSearchRequest,
    ZhihuSearchResult,
    ZhihuStatus,
)
from zhijing.settings_ui import guard

router = APIRouter(prefix="/zhihu", tags=["知乎搜索"], dependencies=[Depends(guard)])


@router.get("/status", response_model=ZhihuStatus)
def configuration_status(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    runtime = request.app.state.runtime
    with runtime.lock:
        return ZhihuStatus(configured=bool(runtime.settings.zhihu_access_secret))


async def read_configuration(request: Request) -> ZhihuConfiguration:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("invalid_zhihu_config", "请使用 JSON 配置请求。", 415)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            raise DomainError("invalid_zhihu_config", "知乎配置内容过大。", 413)
    try:
        return ZhihuConfiguration.model_validate_json(bytes(body))
    except (ValidationError, ValueError):
        raise DomainError("invalid_zhihu_config", "知乎密钥配置无效，请检查输入。", 422) from None


def configure(runtime, config: ZhihuConfiguration) -> ZhihuStatus:
    secret = config.access_secret.get_secret_value().strip()
    with runtime.lock:
        settings = replace(runtime.settings, zhihu_access_secret=secret)
        revision = runtime.revision
    if errors := settings.validation_errors():
        raise DomainError("invalid_zhihu_config", " ".join(errors), 422)
    candidate = build_container(settings)
    try:
        # No authentication probe here: only an explicit search consumes search quota.
        runtime.activate(settings, candidate, expected_revision=revision)
    except Exception:
        candidate.close()
        raise
    return ZhihuStatus(configured=bool(secret))


@router.post("/config", response_model=ZhihuStatus)
async def apply_configuration(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    config = await read_configuration(request)
    return await run_in_threadpool(configure, request.app.state.runtime, config)


@router.post("/search", response_model=ZhihuSearchResult)
def search(body: ZhihuSearchRequest, response: Response, container=Depends(get_container)):
    response.headers["Cache-Control"] = "no-store"
    return container.zhihu.search(body.query, body.count)
