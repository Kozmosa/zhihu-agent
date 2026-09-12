"""Local guarded endpoints for question-answer browser collection jobs."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from zhijing.core.errors import DomainError
from zhijing.features.zhihu.question_models import QuestionJobView, QuestionStartRequest
from zhijing.settings_ui import guard

router = APIRouter(
    prefix="/zhihu/questions/jobs", tags=["知乎问题读取"], dependencies=[Depends(guard)]
)


def _manager(request: Request):
    manager = getattr(request.app.state, "zhihu_questions", None)
    if manager is None:
        raise DomainError(
            "zhihu_question_unavailable", "当前服务不支持知乎问题读取，请更新并重启知境。", 503
        )
    return manager


@router.post("", response_model=QuestionJobView)
async def start_question_job(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("invalid_zhihu_question", "请使用 JSON 提交知乎问题链接。", 415)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 8192:
            raise DomainError(
                "invalid_zhihu_question", "请求内容过大，请只填写问题链接和读取数量。", 413
            )
    try:
        body = QuestionStartRequest.model_validate_json(bytes(content))
    except (ValidationError, ValueError):
        raise DomainError(
            "invalid_zhihu_question", "问题链接或读取数量无效，请检查输入。", 422
        ) from None
    return await run_in_threadpool(_manager(request).start, body.url, body.count)


@router.get("/{job_id}", response_model=QuestionJobView)
def question_job_status(job_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _manager(request).status(job_id)


@router.post("/{job_id}/cancel", response_model=QuestionJobView)
def cancel_question_job(job_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _manager(request).cancel(job_id)
