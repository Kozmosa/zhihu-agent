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
        description="本地知识助手 Server。保留阅读、问答、卡片、审查和思维导图；知识地图围绕问题比较不同回答的观点，需启用模型。",
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        # Browsers must not use a third-party page to invoke the user's local API.
        # Local scripts have no Origin/Fetch Metadata and remain supported.
        is_api = request.url.path.startswith("/api/")
        origin = request.headers.get("origin")
        if is_api and (
            (origin is not None and origin != str(request.base_url).rstrip("/"))
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "invalid_origin", "message": "请从本机知境页面操作。"}},
                headers={"Cache-Control": "no-store"},
            )
        response = await call_next(request)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
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
