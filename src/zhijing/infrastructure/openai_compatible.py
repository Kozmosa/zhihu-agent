"""Chat Completions transport with the existing strict evidence validation."""

import httpx
from .transcript_context import get_context

from zhijing.core.errors import DomainError
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.ollama_transport import system_prompt


class OpenAICompatibleTransport:
    def __init__(
        self,
        client: httpx.Client,
        model: str,
        num_predict: int,
        num_ctx: int,
        thinking: str = "auto",
    ):
        if thinking not in {"auto", "enabled", "disabled"}:
            raise ValueError("thinking must be auto, enabled, or disabled")
        self.client, self.model = client, model
        self.num_predict, self.num_ctx = num_predict, num_ctx
        self.thinking = thinking

    def request(self, *, prompt: str, instructions: str, output_format: dict | str | None) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt(instructions)},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": self.num_predict,
        }
        if output_format is not None:
            body["response_format"] = {"type": "json_object"}
        if self.thinking != "auto":
            body["thinking"] = {"type": self.thinking}
        ctx = get_context()
        if ctx:
            ctx.transcript.append(session_id=ctx.session_id, run_id=ctx.run_id, step_id=ctx.step_id, attempt=ctx.attempt, event="request", provider="openai", model=self.model, payload={"prompt": prompt, "instructions": instructions})
        try:
            response = self.client.post("chat/completions", json=body)
            response.raise_for_status()
            if ctx:
                ctx.transcript.append(session_id=ctx.session_id, run_id=ctx.run_id, step_id=ctx.step_id, attempt=ctx.attempt, event="response", provider="openai", model=self.model, payload={"response": response.text})
        except httpx.TimeoutException as exc:
            raise DomainError(
                "model_timeout", "模型调用超时，请检查服务或调整超时设置。", 502
            ) from exc
        except httpx.HTTPStatusError as exc:
            messages = {
                401: "API 鉴权失败，请检查密钥。",
                403: "API 拒绝访问，请检查密钥权限或服务区域。",
                404: "未找到接口或模型，请检查 Base URL 和模型名。",
                429: "API 限流或额度不足，请检查账户后再试。",
            }
            raise DomainError(
                "model_unavailable",
                messages.get(
                    exc.response.status_code, "模型服务拒绝请求，请检查模型名、输出格式和参数支持。"
                ),
                502,
            ) from exc
        except httpx.HTTPError as exc:
            raise DomainError(
                "model_unavailable", "无法连接模型服务，请检查地址及网络。", 502
            ) from exc
        try:
            choice = response.json()["choices"][0]
            text = choice["message"]["content"]
            if choice.get("finish_reason") != "stop":
                raise ValueError("Generation incomplete or refused")
            if not isinstance(text, str) or not text.strip() or len(text) > 256_000:
                raise ValueError("Invalid response text")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise DomainError(
                "model_invalid_response", "模型响应缺失、超限、被拒绝或未完成生成。", 502
            ) from exc
        return text


class OpenAICompatibleGenerator(OllamaGenerator):
    mode = "openai"

    def __init__(self, client: httpx.Client, model: str, *, thinking: str = "auto", **kwargs):
        super().__init__(client, model, **kwargs)
        self.transport = OpenAICompatibleTransport(
            client, model, kwargs.get("num_predict", 4096), kwargs.get("num_ctx", 32768), thinking
        )
