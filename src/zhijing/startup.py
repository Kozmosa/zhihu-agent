"""Read-only startup checks, separated from HTTP serving and browser integration."""

import importlib
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from zhijing.core.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = ("fastapi", "pydantic", "uvicorn", "httpx", "genanki")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_local_env(env_file: Path | None = None) -> Path | None:
    """Read a local .env into the process environment; explicit variables always win."""
    # Packaged desktop builds deliberately carry no personal credentials.
    if getattr(sys, "frozen", False):
        return None
    path = env_file if env_file is not None else PROJECT_ROOT / ".env"
    if not path.is_file():
        return None
    for raw in path.read_text("utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not _ENV_KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return path


def normalize_data_directory() -> None:
    """Interpret a relative configured data directory against the project root."""
    configured = os.getenv("ZHIJING_DATA_DIR")
    if configured and not Path(configured).is_absolute():
        os.environ["ZHIJING_DATA_DIR"] = str((PROJECT_ROOT / configured).resolve())


def check_environment() -> dict:
    load_local_env()
    normalize_data_directory()
    errors = []
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        errors.append(str(exc))
        settings = Settings(
            data_dir=Path(os.getenv("ZHIJING_DATA_DIR", "E:/CzCode/codex/state/zhijing"))
        )
    if sys.version_info < (3, 12):  # noqa: UP036 - entry point also diagnoses an older interpreter
        errors.append("Python 3.12 or newer is required.")
    dependencies = {}
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
            dependencies[name] = version(name)
        except (ImportError, PackageNotFoundError) as exc:
            errors.append(f"Dependency unavailable: {name}: {exc}")
    errors.extend(settings.validation_errors())
    if not errors:
        try:
            importlib.import_module("zhijing.app")
        except ImportError as exc:
            errors.append(f"Application import failed: {exc}")
    return {
        "ready": not errors,
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "project_root": str(PROJECT_ROOT),
        "data_dir": str(settings.data_dir),
        "model_provider": settings.model_provider,
        "dependencies": dependencies,
        "errors": errors,
        "scope": "Imports and configuration only; database, port and model service are not probed.",
    }
