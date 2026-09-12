"""Local configuration API. Credentials are transient and never included in responses."""

import secrets
from dataclasses import replace
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from zhijing.container import build_container
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.domain.models import Schema
from zhijing.runtime import Runtime

router = APIRouter()


class ModelConfiguration(Schema):
    provider: Literal["extractive", "ollama", "openai"]
    base_url: str = Field(default="", max_length=2048)
    model: str = Field(default="", max_length=200)
    api_key: SecretStr = Field(default_factory=lambda: SecretStr(""))
    output_format: Literal["schema", "json", "prompt"] = "json"
    timeout: float = Field(default=120, ge=1, le=1800, allow_inf_nan=False)
    max_tokens: int = Field(default=4096, ge=256, le=32768)
    context_window: int = Field(default=32768, ge=2048, le=262144)
    max_input_chars: int = Field(default=120000, ge=1000, le=1000000)
    thinking: Literal["auto", "enabled", "disabled"] = "auto"

    def settings(self, initial: Settings) -> Settings:
        # Clear both previous provider credentials when replacing a configuration.
        initial = replace(initial, ollama_api_key="", openai_api_key="")
        if self.provider == "extractive":
            return replace(initial, model_provider="extractive")
        prefix = self.provider
        values = {
            f"{prefix}_url": self.base_url.strip().rstrip("/"),
            f"{prefix}_model": self.model.strip(),
            f"{prefix}_api_key": self.api_key.get_secret_value(),
            f"{prefix}_format": self.output_format,
            f"{prefix}_timeout": self.timeout,
            f"{prefix}_max_input_chars": self.max_input_chars,
            f"{prefix}_{'num_predict' if prefix == 'ollama' else 'max_tokens'}": self.max_tokens,
            f"{prefix}_{'num_ctx' if prefix == 'ollama' else 'context_window'}": self.context_window,
        }
        configured = replace(initial, model_provider=self.provider, **values)
        if self.provider == "openai":
            configured = replace(configured, openai_thinking=self.thinking)
        if errors := configured.validation_errors():
            raise DomainError("invalid_model_config", " ".join(errors), 422)
        return configured


class ConnectionResult(Schema):
    status: Literal["ok"]


def guard(request: Request):
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise DomainError("local_only", "配置页仅允许本机访问。", 403)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise DomainError("invalid_origin", "请从本机配置页操作。", 403)
    if request.method == "POST":
        token = request.headers.get("x-zhijing-token", "")
        if not secrets.compare_digest(token, request.app.state.config_token):
            raise DomainError("invalid_config_token", "页面会话已失效，请刷新配置页。", 403)


@router.get("/", include_in_schema=False, dependencies=[Depends(guard)])
def configuration_page(request: Request):
    return render_page(request, "settings.html")


def render_page(request: Request, filename: str):
    web = Path(__file__).with_name("web")
    template = web.joinpath(filename).read_text("utf-8")
    widget = web.joinpath("chat.html").read_text("utf-8")
    # Insert first so shared scripts receive the same nonce as the page and its CSP.
    template = template.replace("__CHAT_WIDGET__", widget)
    return HTMLResponse(
        template.replace("__CONFIG_TOKEN__", request.app.state.config_token),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'nonce-"
            + request.app.state.config_token
            + "'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/workspace", include_in_schema=False, dependencies=[Depends(guard)])
def workspace_page(request: Request):
    return render_page(request, "workspace.html")


@router.get("/assets/{filename}", include_in_schema=False, dependencies=[Depends(guard)])
def workspace_asset(filename: str):
    if filename not in {
        "workspace.js",
        "workspace.css",
        "chat-widget.js",
        "chat-widget.css",
        "zhihu-companion.user.js",
    }:
        raise DomainError("asset_not_found", "未找到页面资源。", 404)
    return FileResponse(
        Path(__file__).with_name("web") / filename,
        media_type="text/javascript" if filename.endswith(".js") else "text/css",
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/v1/settings/model", tags=["模型配置"], dependencies=[Depends(guard)])
def configuration_status(request: Request):
    runtime = request.app.state.runtime
    with runtime.lock:
        settings = runtime.settings
        provider = settings.model_provider
        prefix = provider if provider != "extractive" else "openai"
        return {
            "provider": provider,
            "base_url": getattr(settings, f"{prefix}_url"),
            "model": getattr(settings, f"{prefix}_model"),
            "has_api_key": bool(getattr(settings, f"{prefix}_api_key")),
            "output_format": getattr(settings, f"{prefix}_format"),
            "timeout": getattr(settings, f"{prefix}_timeout"),
            "max_tokens": settings.ollama_num_predict
            if prefix == "ollama"
            else settings.openai_max_tokens,
            "context_window": settings.ollama_num_ctx
            if prefix == "ollama"
            else settings.openai_context_window,
            "max_input_chars": getattr(settings, f"{prefix}_max_input_chars"),
            "persistence": "session_only",
            "thinking": settings.openai_thinking if provider == "openai" else "auto",
        }


async def read_configuration(request: Request) -> ModelConfiguration:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise DomainError("invalid_model_config", "请使用 JSON 配置请求。", 415)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise DomainError("invalid_model_config", "配置内容过大。", 413)
    try:
        return ModelConfiguration.model_validate_json(bytes(body))
    except (ValidationError, ValueError):
        # Default FastAPI validation responses include input values, including secrets.
        raise DomainError(
            "invalid_model_config", "配置字段无效，请检查协议、地址、模型、密钥和数值范围。", 422
        ) from None


def configure(runtime: Runtime, config: ModelConfiguration, activate: bool):
    with runtime.lock:
        settings = config.settings(runtime.settings)
        revision = runtime.revision
    candidate = build_container(settings)
    try:
        if config.provider != "extractive":
            candidate.reader.generator.generate(
                task="connection_test",
                instructions='仅返回 JSON 对象 {"status":"ok"}。',
                payload={"message": "ZhiJing connection test"},
                response_model=ConnectionResult,
            )
        if activate:
            runtime.activate(settings, candidate, expected_revision=revision)
    except Exception:
        candidate.close()
        raise
    if not activate:
        candidate.close()
    return {
        "status": "ok",
        "provider": config.provider,
        "activated": activate,
        "message": "已启用离线模式。"
        if config.provider == "extractive"
        else (
            "连接及 JSON 输出测试通过，配置已启用。"
            if activate
            else "连接及 JSON 输出测试通过，当前配置未变。"
        ),
        "scope": "仅验证短文本连接与 JSON 输出；五项业务的真实模型效果仍需逐项试用。",
    }


@router.post("/api/v1/settings/model/test", tags=["模型配置"], dependencies=[Depends(guard)])
async def test_configuration(request: Request):
    config = await read_configuration(request)
    return await run_in_threadpool(configure, request.app.state.runtime, config, False)


@router.post("/api/v1/settings/model/apply", tags=["模型配置"], dependencies=[Depends(guard)])
async def apply_configuration(request: Request):
    config = await read_configuration(request)
    return await run_in_threadpool(configure, request.app.state.runtime, config, True)
