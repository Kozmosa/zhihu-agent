"""配置只在创建应用时读取，导入模块不会创建数据库或连接网络。"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_provider: str = "extractive"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_api_key: str = field(default="", repr=False)
    ollama_timeout: float = 120
    ollama_format: str = "schema"
    ollama_max_input_chars: int = 120000
    ollama_num_predict: int = 4096
    ollama_num_ctx: int = 32768
    openai_url: str = "https://api.deepseek.com/v1"
    openai_model: str = ""
    openai_api_key: str = field(default="", repr=False)
    openai_timeout: float = 120
    openai_format: str = "json"
    openai_max_input_chars: int = 120000
    openai_max_tokens: int = 4096
    openai_context_window: int = 32768
    openai_thinking: str = "auto"
    zhihu_url: ClassVar[str] = "https://developer.zhihu.com/api/v1/content/zhihu_search"
    zhihu_access_secret: str = field(default="", repr=False)
    zhihu_timeout: float = 20

    def validation_errors(self) -> list[str]:
        errors = []
        if len(self.zhihu_access_secret) > 4096 or any(
            not 33 <= ord(character) <= 126 for character in self.zhihu_access_secret
        ):
            errors.append("知乎 Access Secret 格式无效，请重新复制密钥。")
        if not math.isfinite(self.zhihu_timeout) or not 1 <= self.zhihu_timeout <= 120:
            errors.append("ZHIHU_SEARCH_TIMEOUT 必须在 1 到 120 秒之间。")
        if self.model_provider not in {"extractive", "ollama", "openai"}:
            errors.append("ZHIJING_MODEL_PROVIDER must be extractive, ollama, or openai.")
        if self.model_provider == "openai":
            if self.openai_thinking not in {"auto", "enabled", "disabled"}:
                errors.append("ZHIJING_OPENAI_THINKING must be auto, enabled, or disabled.")
            # Reuse the same URL, credential and budget validation for both protocols.
            mapped = Settings(
                data_dir=self.data_dir,
                model_provider="ollama",
                ollama_url=self.openai_url,
                ollama_model=self.openai_model,
                ollama_api_key=self.openai_api_key,
                ollama_timeout=self.openai_timeout,
                ollama_format=self.openai_format,
                ollama_max_input_chars=self.openai_max_input_chars,
                ollama_num_predict=self.openai_max_tokens,
                ollama_num_ctx=self.openai_context_window,
            )
            errors.extend(
                error.replace("OLLAMA", "OPENAI")
                .replace("NUM_PREDICT", "MAX_TOKENS")
                .replace("NUM_CTX", "CONTEXT_WINDOW")
                for error in mapped.validation_errors()
            )
            if self.openai_format not in {"json", "prompt"}:
                errors.append("ZHIJING_OPENAI_FORMAT must be json or prompt.")
            return errors
        if self.ollama_format not in {"schema", "json", "prompt"}:
            errors.append("ZHIJING_OLLAMA_FORMAT must be schema, json, or prompt.")
        if not self.ollama_model.strip():
            errors.append("ZHIJING_OLLAMA_MODEL must not be blank.")
        try:
            url = urlsplit(self.ollama_url)
            valid_url = (
                url.scheme in {"http", "https"}
                and url.hostname
                and not (url.username or url.password or url.query or url.fragment)
            )
            valid_url = valid_url and not any(c.isspace() for c in self.ollama_url)
            if url.path.rstrip("/").endswith(("/api/generate", "/api/chat", "/chat/completions")):
                errors.append(
                    "ZHIJING_OLLAMA_URL must be a base URL, not a generate/chat endpoint."
                )
            _ = url.port
        except ValueError:
            valid_url = False
        if not valid_url:
            errors.append(
                "ZHIJING_OLLAMA_URL must be an HTTP(S) base URL without credentials, query or fragment."
            )
        if not math.isfinite(self.ollama_timeout) or not 1 <= self.ollama_timeout <= 1800:
            errors.append("ZHIJING_OLLAMA_TIMEOUT must be between 1 and 1800 seconds.")
        if not 1000 <= self.ollama_max_input_chars <= 1000000:
            errors.append("ZHIJING_OLLAMA_MAX_INPUT_CHARS must be between 1000 and 1000000.")
        if not 256 <= self.ollama_num_predict <= 32768:
            errors.append("ZHIJING_OLLAMA_NUM_PREDICT must be between 256 and 32768.")
        if (
            not 2048 <= self.ollama_num_ctx <= 262144
            or self.ollama_num_ctx <= self.ollama_num_predict + 512
        ):
            errors.append(
                "ZHIJING_OLLAMA_NUM_CTX must be 2048..262144 and exceed NUM_PREDICT plus 512."
            )
        if any(not 32 <= ord(c) <= 126 for c in self.ollama_api_key):
            errors.append("ZHIJING_OLLAMA_API_KEY must contain only printable ASCII characters.")
        return errors

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("ZHIJING_DATA_DIR", "E:/CzCode/codex/state/zhijing")),
            zhihu_access_secret=os.getenv("ZHIHU_ACCESS_SECRET", "").strip(),
            zhihu_timeout=_number("ZHIHU_SEARCH_TIMEOUT", "20", float),
            model_provider=os.getenv("ZHIJING_MODEL_PROVIDER", "extractive"),
            ollama_url=os.getenv("ZHIJING_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("ZHIJING_OLLAMA_MODEL", "qwen3:8b"),
            ollama_api_key=os.getenv("ZHIJING_OLLAMA_API_KEY", ""),
            ollama_timeout=_number("ZHIJING_OLLAMA_TIMEOUT", "120", float),
            ollama_format=os.getenv("ZHIJING_OLLAMA_FORMAT", "schema"),
            ollama_max_input_chars=_number("ZHIJING_OLLAMA_MAX_INPUT_CHARS", "120000", int),
            ollama_num_predict=_number("ZHIJING_OLLAMA_NUM_PREDICT", "4096", int),
            ollama_num_ctx=_number("ZHIJING_OLLAMA_NUM_CTX", "32768", int),
            openai_url=os.getenv("ZHIJING_OPENAI_URL", "https://api.deepseek.com/v1"),
            openai_model=os.getenv("ZHIJING_OPENAI_MODEL", ""),
            openai_api_key=os.getenv("ZHIJING_OPENAI_API_KEY", ""),
            openai_timeout=_number("ZHIJING_OPENAI_TIMEOUT", "120", float),
            openai_format=os.getenv("ZHIJING_OPENAI_FORMAT", "json"),
            openai_max_input_chars=_number("ZHIJING_OPENAI_MAX_INPUT_CHARS", "120000", int),
            openai_max_tokens=_number("ZHIJING_OPENAI_MAX_TOKENS", "4096", int),
            openai_context_window=_number("ZHIJING_OPENAI_CONTEXT_WINDOW", "32768", int),
            openai_thinking=os.getenv("ZHIJING_OPENAI_THINKING", "auto"),
        )


def _number(name: str, default: str, converter):
    try:
        return converter(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number.") from exc
