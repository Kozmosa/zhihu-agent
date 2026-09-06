"""配置只在创建应用时读取，导入模块不会创建数据库或连接网络。"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
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

    def validation_errors(self) -> list[str]:
        errors = []
        if self.model_provider not in {"extractive", "ollama"}:
            errors.append("ZHIJING_MODEL_PROVIDER must be extractive or ollama.")
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
            model_provider=os.getenv("ZHIJING_MODEL_PROVIDER", "extractive"),
            ollama_url=os.getenv("ZHIJING_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("ZHIJING_OLLAMA_MODEL", "qwen3:8b"),
            ollama_api_key=os.getenv("ZHIJING_OLLAMA_API_KEY", ""),
            ollama_timeout=_number("ZHIJING_OLLAMA_TIMEOUT", "120", float),
            ollama_format=os.getenv("ZHIJING_OLLAMA_FORMAT", "schema"),
            ollama_max_input_chars=_number("ZHIJING_OLLAMA_MAX_INPUT_CHARS", "120000", int),
            ollama_num_predict=_number("ZHIJING_OLLAMA_NUM_PREDICT", "4096", int),
            ollama_num_ctx=_number("ZHIJING_OLLAMA_NUM_CTX", "32768", int),
        )


def _number(name: str, default: str, converter):
    try:
        return converter(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid number.") from exc
