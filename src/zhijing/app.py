import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from zhijing import __version__
from zhijing.api import router
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.features.zhihu.question_jobs import QuestionJobs
from zhijing.runtime import Runtime
from zhijing.settings_ui import router as settings_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(settings)
        app.state.config_token = secrets.token_urlsafe(32)
        project_root = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        app.state.zhihu_questions = QuestionJobs(settings.data_dir, project_root)
        try:
            yield
        finally:
            app.state.zhihu_questions.close()
            app.state.runtime.close()

    app = FastAPI(
        title="知境 ZhiJing Agent",
        version=__version__,
        lifespan=lifespan,
        description="本地知识助手 Server。五项能力支持 Ollama 和 OpenAI 兼容 API，默认离线摘录；companion/run 同步组合，runs 提供运行历史、部分结果及恢复。",
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.middleware("http")
    async def require_api_token(request: Request, call_next):
        # Opt-in gate for non-local clients; local pages and the platform health check stay open.
        if settings.api_token:
            path = request.url.path
            local_client = (
                request.client is not None and request.client.host in {"127.0.0.1", "::1"}
            )
            protected = path.startswith("/api/v1/") and not path.startswith("/api/v1/settings/")
            if protected and not local_client:
                provided = request.headers.get("authorization", "").encode("utf-8", "replace")
                expected = f"Bearer {settings.api_token}".encode()
                if not secrets.compare_digest(provided, expected):
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": {
                                "code": "invalid_api_token",
                                "message": "缺少或错误的访问令牌，请携带 Authorization: Bearer 令牌重试。",
                            }
                        },
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return await call_next(request)

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver", *settings.allowed_hosts],
    )

    @app.middleware("http")
    async def no_cache_settings(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/settings/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", tags=["运行状态"])
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "model_provider": app.state.runtime.settings.model_provider,
        }

    app.include_router(router)
    app.include_router(settings_router)
    return app
