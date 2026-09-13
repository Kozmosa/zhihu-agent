"""Separate immutable bundled resources from the desktop user's persistent state."""

import os
import sys
from pathlib import Path


def user_state_directory() -> Path:
    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "ZhiJing").resolve()


def default_data_directory(project_root: Path) -> Path:
    base = user_state_directory() if getattr(sys, "frozen", False) else Path(project_root)
    configured = os.getenv("ZHIJING_DATA_DIR", "").strip()
    path = Path(configured) if configured else Path("data")
    return (path if path.is_absolute() else base / path).resolve()
