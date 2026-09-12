# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir bundle: application code, public assets and dependency metadata only."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

project = Path(SPECPATH).parent
source = project / "src"
package = source / "zhijing"
sys.path.insert(0, str(source))
name = os.getenv("ZHIJING_BUILD_NAME", "知境")
icon = Path(os.getenv("ZHIJING_BUILD_ICON", str(package / "assets" / "liukanshan.ico")))
if not icon.is_file():
    raise FileNotFoundError("The application icon must exist before building: " + str(icon))

datas = []
for folder, extensions in (
    ("web", {".html", ".js", ".css"}),
    ("assets", {".png", ".ico", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}),
):
    for asset in sorted((package / folder).rglob("*")):
        if asset.is_file() and (asset.suffix.lower() in extensions or asset.name == "ATTRIBUTION.md"):
            destination = Path("zhijing") / asset.parent.relative_to(package)
            datas.append((str(asset), str(destination)))

# check_environment uses importlib.metadata; frozen code still performs a real dependency check.
dependencies = ("fastapi", "pydantic", "uvicorn", "httpx", "genanki")
for dependency in dependencies:
    datas.extend(copy_metadata(dependency, recursive=True))

a = Analysis(
    [str(project / "desktop.py")],
    pathex=[str(source)],
    binaries=[],
    datas=datas,
    hiddenimports=list(dependencies) + collect_submodules("uvicorn"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "ruff", "pip", "setuptools", "wheel"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
