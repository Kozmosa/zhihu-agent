"""配置只在创建应用时读取，导入模块不会创建数据库或连接网络。"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model_provider: str = "extractive"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("ZHIJING_DATA_DIR", "E:/CzCode/codex/state/zhijing")),
            model_provider=os.getenv("ZHIJING_MODEL_PROVIDER", "extractive"),
            ollama_url=os.getenv("ZHIJING_OLLAMA_URL", "http://127.0.0.1:11434"),
            ollama_model=os.getenv("ZHIJING_OLLAMA_MODEL", "qwen3:8b"),
        )
