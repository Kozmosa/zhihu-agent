import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from zhijing import __version__
from zhijing.api import router
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.runtime import Runtime
from zhijing.settings_ui import guard
from zhijing.settings_ui import router as settings_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(settings)
        app.state.config_token = secrets.token_urlsafe(32)
        app.state.session_id = secrets.token_urlsafe(16)
        try:
            yield
        finally:
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

    @app.exception_handler(RequestValidationError)
    async def invalid_request_handler(request: Request, exc: RequestValidationError):
        # Pydantic's default response may contain raw input, including pasted credentials.
        return JSONResponse(
            status_code=422,
            content={
                "error": {"code": "invalid_request", "message": "请求字段无效，请检查输入格式。"}
            },
        )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_api_boundary(request: Request, call_next):
        is_api = request.url.path.startswith("/api/v1/")
        # The installed userscript has a separately scoped, paired receive credential.
        is_capture = (
            request.method == "POST" and request.url.path == "/api/v1/zhihu/companion/receive"
        )
        if is_api and not is_capture:
            try:
                guard(request)
            except DomainError as exc:
                return JSONResponse(
                    status_code=exc.status,
                    content={"error": {"code": exc.code, "message": exc.message}},
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
        response = await call_next(request)
        if is_api:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response

    @app.get("/health", tags=["运行状态"])
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "model_provider": app.state.runtime.settings.model_provider,
            "api_auth": "session-v1",
        }

    app.include_router(router)
    app.include_router(settings_router)
    return app
