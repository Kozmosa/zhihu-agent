"""配置只在创建应用时读取，导入模块不会创建数据库或连接网络。"""

import json
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
    openai_url: str = "https://api.openai-next.com/v1"
    openai_model: str = "deepseek-v4-flash"
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
        data_dir = Path(os.getenv("ZHIJING_DATA_DIR", "E:/CzCode/codex/state/zhijing"))
        local = _local_model_config(data_dir / "model-config.json")
        # An explicit process model configuration replaces the entire saved profile.
        # This avoids sending a saved credential to an overridden endpoint.
        override = any(
            k == "ZHIJING_MODEL_PROVIDER" or k.startswith(("ZHIJING_OPENAI_", "ZHIJING_OLLAMA_"))
            for k in os.environ
        )

        def get(name, default):
            return os.environ.get(name, default if override else local.get(name, default))

        def number(name, default, converter):
            try:
                return converter(get(name, default))
            except ValueError:
                raise ValueError(f"{name} must be a valid number.") from None

        return cls(
            data_dir=Path(get("ZHIJING_DATA_DIR", "E:/CzCode/codex/state/zhijing")),
            zhihu_access_secret=get("ZHIHU_ACCESS_SECRET", "").strip(),
            zhihu_timeout=number("ZHIHU_SEARCH_TIMEOUT", "20", float),
            model_provider=get("ZHIJING_MODEL_PROVIDER", "extractive"),
            ollama_url=get("ZHIJING_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=get("ZHIJING_OLLAMA_MODEL", "qwen3:8b"),
            ollama_api_key=get("ZHIJING_OLLAMA_API_KEY", ""),
            ollama_timeout=number("ZHIJING_OLLAMA_TIMEOUT", "120", float),
            ollama_format=get("ZHIJING_OLLAMA_FORMAT", "schema"),
            ollama_max_input_chars=number("ZHIJING_OLLAMA_MAX_INPUT_CHARS", "120000", int),
            ollama_num_predict=number("ZHIJING_OLLAMA_NUM_PREDICT", "4096", int),
            ollama_num_ctx=number("ZHIJING_OLLAMA_NUM_CTX", "32768", int),
            openai_url=get("ZHIJING_OPENAI_URL", "https://api.openai-next.com/v1"),
            openai_model=get("ZHIJING_OPENAI_MODEL", "deepseek-v4-flash"),
            openai_api_key=get("ZHIJING_OPENAI_API_KEY", ""),
            openai_timeout=number("ZHIJING_OPENAI_TIMEOUT", "120", float),
            openai_format=get("ZHIJING_OPENAI_FORMAT", "json"),
            openai_max_input_chars=number("ZHIJING_OPENAI_MAX_INPUT_CHARS", "120000", int),
            openai_max_tokens=number("ZHIJING_OPENAI_MAX_TOKENS", "4096", int),
            openai_context_window=number("ZHIJING_OPENAI_CONTEXT_WINDOW", "32768", int),
            openai_thinking=get("ZHIJING_OPENAI_THINKING", "auto"),
        )


def _number(name: str, default: str, converter):
    try:
        return converter(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number.") from exc


def _local_model_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 16384:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        allowed = {
            "ZHIJING_MODEL_PROVIDER",
            "ZHIJING_OPENAI_URL",
            "ZHIJING_OPENAI_MODEL",
            "ZHIJING_OPENAI_API_KEY",
            "ZHIJING_OPENAI_TIMEOUT",
            "ZHIJING_OPENAI_FORMAT",
            "ZHIJING_OPENAI_MAX_TOKENS",
            "ZHIJING_OPENAI_CONTEXT_WINDOW",
            "ZHIJING_OPENAI_MAX_INPUT_CHARS",
            "ZHIJING_OPENAI_THINKING",
        }
        if not isinstance(value, dict) or any(
            k not in allowed or not isinstance(v, str) for k, v in value.items()
        ):
            raise ValueError()
        return value
    except (ValueError, OSError):
        raise ValueError(
            "Local model-config.json is invalid or unreadable; check its JSON string fields."
        ) from None
