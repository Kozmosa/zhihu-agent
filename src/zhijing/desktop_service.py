"""Loopback-only service lifecycle and HTTP boundary for the desktop assistant."""

import re
import socket
import time
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from threading import Event, RLock, Thread

import httpx
import uvicorn

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.desktop_paths import default_data_directory


class DesktopServiceError(RuntimeError):
    """A fixed, user-readable error that never includes upstream text or credentials."""


class _PageTokens(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.tokens: set[str] = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attributes = dict(attrs)
        for name in ("data-config-token", "nonce"):
            value = attributes.get(name)
            if value and re.fullmatch(r"[A-Za-z0-9_-]{20,200}", value):
                self.tokens.add(value)


class DesktopService:
    """Reuse an existing ZhiJing server, or own one daemon server within this process."""

    def __init__(self, project_root: Path, port: int = 8000, data_dir: Path | None = None):
        if type(port) is not int or not 1 <= port <= 65535:
            raise DesktopServiceError("服务端口必须是 1 到 65535 之间的整数。")
        self.project_root = Path(project_root).resolve()
        self.data_dir = (
            Path(data_dir).resolve()
            if data_dir is not None
            else default_data_directory(self.project_root)
        )
        self.port = port
        self._lock = RLock()
        self._server: uvicorn.Server | None = None
        self._thread: Thread | None = None
        self._startup_failed = Event()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _request(self, method: str, path: str, *, timeout=30, **kwargs) -> httpx.Response:
        try:
            # A fresh client is safe when Tk worker threads issue overlapping requests.
            with httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(timeout, connect=min(timeout, 3)),
            ) as client:
                response = client.request(method, self.base_url + path, **kwargs)
        except httpx.TimeoutException:
            message = (
                "问答请求等待超时，服务可能仍在处理；没有自动重复发送，请稍后确认。"
                if method == "POST"
                else "本地服务响应超时，请稍后重试。"
            )
            raise DesktopServiceError(message) from None
        except httpx.HTTPError:
            raise DesktopServiceError("无法连接本地知境服务，请确认服务仍在运行。") from None
        if 300 <= response.status_code < 400:
            raise DesktopServiceError("本地服务返回了重定向，已停止请求；请检查端口设置。")
        if response.is_error:
            code = None
            try:
                payload = response.json()
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                code = error.get("code") if isinstance(error, dict) else None
            except ValueError:
                pass
            messages = {
                "source_not_found": "所选资料已不存在，请刷新资料列表。",
                "author_mismatch": "资料信息已变化，请刷新列表并重新选择。",
                "model_timeout": "模型响应超时，请稍后重试；本次请求没有自动重发。",
                "model_unavailable": "模型服务不可用，请打开模型设置检查连接或切换离线模式。",
                "model_invalid_response": "模型未返回有效结果，请核对模型设置后重试。",
                "model_output_truncated": "模型达到输出上限。请减少生成数量，或在模型设置中提高最大输出 Token。",
                "cards_format_invalid": "卡片格式或字段长度不符。请先试生成 1～3 张，或换用支持 JSON 输出的模型。",
                "cards_evidence_invalid": "卡片证据无法在资料原文中找到，请重试或换用其他模型。",
                "model_input_too_large": "当前资料超过模型输入限制，请选择较短的资料。",
                "model_context_exceeded": "当前资料超过模型上下文限制，请检查模型设置。",
                "invalid_config_token": "页面会话已更新，请重新连接本地服务后再试。",
                "storage_busy": "资料库暂时繁忙，请稍后重试。",
            }
            if isinstance(code, str) and code in messages:
                raise DesktopServiceError(messages[code])
            if response.status_code in {401, 403}:
                raise DesktopServiceError("本地服务拒绝访问，请检查服务地址与会话。")
            if response.status_code == 429:
                raise DesktopServiceError("请求过于频繁或额度不足，请稍后重试。")
            if response.status_code == 422:
                raise DesktopServiceError("请求内容无效，请检查所选资料和问题。")
            raise DesktopServiceError("本地服务未能完成请求，请稍后重试。")
        return response

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except ValueError:
            raise DesktopServiceError("本地服务返回了无法识别的响应。") from None

    def get_health(self) -> dict:
        payload = self._json(self._request("GET", "/health", timeout=3))
        if (
            not isinstance(payload, dict)
            or payload.get("status") != "ok"
            or payload.get("model_provider") not in ("extractive", "ollama", "openai")
            or not isinstance(payload.get("version"), str)
            or not re.fullmatch(r"\d+\.\d+\.\d+(?:[A-Za-z0-9.+-]{0,30})", payload["version"])
        ):
            raise DesktopServiceError("该端口没有返回可识别的知境服务状态，请检查端口设置。")
        return {key: payload[key] for key in ("status", "version", "model_provider")}

    def _verify_existing_service(self):
        schema = self._json(self._request("GET", "/openapi.json", timeout=3))
        info = schema.get("info", {}) if isinstance(schema, dict) else {}
        if not isinstance(info, dict) or info.get("title") != "知境 ZhiJing Agent":
            raise DesktopServiceError("该端口被其他服务占用，请选择空闲端口；原服务未被修改。")
        required = {
            "/api/v1/sources/groups",
            "/api/v1/sources/delete",
            "/api/v1/zhihu/questions/jobs",
        }
        paths = schema.get("paths", {})
        if not isinstance(paths, dict) or not required.issubset(paths):
            raise DesktopServiceError(
                "当前端口运行的是旧版知境，缺少资料管理或作者读取组件。请先处理待导入资料并退出旧服务，再启动新版；原服务未被修改。"
            )

    def _port_is_occupied(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                return True
        except OSError:
            return False

    def ensure_running(self) -> dict:
        with self._lock:
            try:
                health = self.get_health()
            except DesktopServiceError:
                if self._port_is_occupied():
                    raise DesktopServiceError(
                        "该端口已被占用或服务尚未就绪，请稍后重试或选择其他端口；原服务未被修改。"
                    ) from None
            else:
                self._verify_existing_service()
                return health
            if self._thread is not None and self._thread.is_alive():
                raise DesktopServiceError("本地服务正在启动或退出，请稍后重试。")

            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Reserve before starting Uvicorn, so a competing process cannot be displaced.
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind(("127.0.0.1", self.port))
            except OSError:
                listener.close()
                raise DesktopServiceError(
                    "无法使用该端口，请选择空闲端口；没有停止或替换其他服务。"
                ) from None
            try:
                settings = replace(Settings.from_env(), data_dir=self.data_dir)
                if settings.validation_errors():
                    raise DesktopServiceError("本地服务配置无效，请检查模型及环境变量设置。")
                app = create_app(settings)
                server = uvicorn.Server(
                    uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=self.port,
                        access_log=False,
                        log_config=None,
                        log_level="critical",
                        timeout_graceful_shutdown=10,
                    )
                )
            except Exception:
                listener.close()
                raise DesktopServiceError(
                    "无法创建本地服务，请检查环境配置和资料目录的读写权限。"
                ) from None

            self._startup_failed.clear()
            self._server = server

            def serve():
                try:
                    server.run(sockets=[listener])
                except BaseException:
                    # Uvicorn can raise SystemExit at startup; do not terminate the desktop UI.
                    self._startup_failed.set()
                finally:
                    listener.close()

            self._thread = Thread(target=serve, name="zhijing-desktop-service", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self._startup_failed.is_set() or not self._thread.is_alive():
                    break
                if server.started:
                    try:
                        return self.get_health()
                    except DesktopServiceError:
                        pass
                self._startup_failed.wait(0.05)
            self.shutdown()
            raise DesktopServiceError(
                "本地服务未能启动，请检查环境依赖、端口和资料目录的读写权限。"
            )

    def list_sources(self, offset: int = 0, limit: int = 21) -> list[dict]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise DesktopServiceError("资料列表分页参数无效。")
        payload = self._json(
            self._request("GET", "/api/v1/sources", params={"offset": offset, "limit": limit})
        )
        if not isinstance(payload, list) or any(
            not isinstance(source, dict)
            or not isinstance(source.get("id"), str)
            or not isinstance(source.get("author_id"), str)
            for source in payload
        ):
            raise DesktopServiceError("本地服务返回的资料列表无效，请刷新后重试。")
        return payload

    def ask(self, source: dict, question: str) -> dict:
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("id"), str)
            or not 1 <= len(source["id"].strip()) <= 200
            or not isinstance(source.get("author_id"), str)
            or not 1 <= len(source["author_id"].strip()) <= 200
        ):
            raise DesktopServiceError("请先选择一份有效资料。")
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise DesktopServiceError("请输入 1 到 2000 个字符的问题。")
        page = self._request("GET", "/workspace", timeout=10)
        tokens = _PageTokens(page.text).tokens
        if len(tokens) != 1:
            raise DesktopServiceError("无法读取本地页面会话，请检查服务版本后重试。")
        token = next(iter(tokens))
        payload = self._json(
            self._request(
                "POST",
                "/api/v1/author/ask",
                timeout=300,
                headers={"X-Zhijing-Token": token, "Origin": self.base_url},
                json={
                    "author_id": source["author_id"],
                    "primary_source_id": source["id"],
                    "question": question.strip(),
                },
            )
        )
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("answer"), str)
            or not isinstance(payload.get("citations"), list)
            or payload.get("mode") not in ("extractive", "ollama", "openai")
        ):
            raise DesktopServiceError("问答服务返回了无效结果，请稍后重试。")
        return payload

    def shutdown(self) -> None:
        with self._lock:
            # Reusing an existing endpoint never creates these owned-server references.
            server, thread = self._server, self._thread
            if server is None or thread is None:
                return
            server.should_exit = True
            thread.join(timeout=12)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=3)
            if thread.is_alive():
                raise DesktopServiceError("本地服务仍在结束当前请求，请稍后再次退出。")
            self._server = None
            self._thread = None
