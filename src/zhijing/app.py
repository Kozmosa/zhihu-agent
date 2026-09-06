from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from zhijing.api import router
from zhijing.container import build_container
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = build_container(settings)
        try:
            yield
        finally:
            app.state.container.close()

    app = FastAPI(
        title="知境 ZhiJing Agent",
        version="0.1.0",
        lifespan=lifespan,
        description="本地阅读助手 Server。默认离线摘录；通过 /api/v1/companion/run 组合功能。",
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    @app.get("/health", tags=["运行状态"])
    def health():
        return {"status": "ok", "version": "0.1.0", "model_provider": settings.model_provider}

    app.include_router(router)
    return app
