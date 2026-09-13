"""Build a self-contained Windows folder using this interpreter's isolated build environment."""

import argparse
import ast
import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def audit_module_sources(work: Path) -> int:
    found = {}

    def visit(value):
        if isinstance(value, (tuple, list)):
            if (
                len(value) == 3
                and isinstance(value[0], str)
                and (value[0] == "zhijing" or value[0].startswith("zhijing."))
                and isinstance(value[1], str)
                and value[2] in {"PYMODULE", "PYMODULE-1", "PYMODULE-2"}
            ):
                location = Path(value[1]).resolve()
                if not location.is_relative_to((PROJECT / "src" / "zhijing").resolve()):
                    raise RuntimeError("An application module was collected from another checkout.")
                found[value[0]] = str(location)
            for child in value:
                visit(child)

    for toc in work.rglob("Analysis-00.toc"):
        visit(ast.literal_eval(toc.read_text("utf-8")))
    if not found:
        raise RuntimeError("No application modules found in the PyInstaller analysis record.")
    return len(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-path", type=Path, default=PROJECT / "dist")
    parser.add_argument("--work-path", type=Path, default=PROJECT / "build" / "desktop")
    parser.add_argument("--name", default="知境")
    parser.add_argument("--icon", type=Path, default=PROJECT / "src/zhijing/assets/liukanshan.ico")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace this app's existing build"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows executables must be built with Windows Python.")
    if (
        not args.name
        or any(character in args.name for character in '\\/:*?"<>|')
        or args.name in {".", ".."}
    ):
        parser.error("--name must be one valid Windows directory name.")
    icon = args.icon.resolve()
    if not icon.is_file():
        parser.error("The .ico file is missing; create the desktop assets before building.")
    versions = {}
    for dependency in (
        "pyinstaller",
        "fastapi",
        "pydantic",
        "uvicorn",
        "httpx",
        "genanki",
        "pywebview",
        "pythonnet",
    ):
        try:
            versions[dependency] = version(dependency)
        except PackageNotFoundError:
            parser.error(f"Install {dependency} in the build interpreter first.")
    dist, work = args.dist_path.resolve(), args.work_path.resolve()
    if (dist / args.name).exists() and not args.overwrite:
        parser.error(
            "The output application folder already exists; choose a new path or --overwrite."
        )
    environment = os.environ.copy()
    for private in (
        "ZHIHU_ACCESS_SECRET",
        "ZHIJING_OPENAI_API_KEY",
        "ZHIJING_OLLAMA_API_KEY",
        "ZHIJING_DATA_DIR",
    ):
        environment.pop(private, None)
    environment.update(
        PYTHONNOUSERSITE="1",
        PYTHONUSERBASE=str(work / "isolated-user-base"),
        PYTHONPATH=str(PROJECT / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        ZHIJING_BUILD_NAME=args.name,
        ZHIJING_BUILD_ICON=str(icon),
    )
    # A venv based on Conda does not automatically expose its base runtime DLLs.
    dll_search = [
        Path(sys.base_prefix) / "Library" / "bin",
        Path(sys.base_prefix) / "DLLs",
        Path(sys.base_prefix),
    ]
    environment["PATH"] = os.pathsep.join(
        [str(folder) for folder in dll_search if folder.is_dir()] + [environment.get("PATH", "")]
    )
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--noconfirm",
        str(PROJECT / "packaging" / "zhijing.spec"),
    ]
    subprocess.run(command, cwd=PROJECT, env=environment, check=True)
    executable = dist / args.name / (args.name + ".exe")
    if not executable.is_file():
        raise RuntimeError("PyInstaller did not produce the expected executable.")
    module_count = audit_module_sources(work)
    report = {
        "format": "windows-onedir",
        "executable": str(executable),
        "build_python": sys.version.split()[0],
        "dependencies": versions,
        "default_user_data": "%LOCALAPPDATA%/ZhiJing/data",
        "bundled_project_data": False,
        "application_modules_from_selected_project": module_count,
        "note": "Distribute the entire application folder, including _internal.",
        "system_runtime": "Microsoft Edge WebView2 Runtime and .NET Framework 4.6.2 or later",
    }
    work.mkdir(parents=True, exist_ok=True)
    (work / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
