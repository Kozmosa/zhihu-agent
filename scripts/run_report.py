"""执行实测并生成项目内报告：python scripts/run_report.py。"""

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from reporting.http_runner import run_http
from reporting.render_report import write_reports
from reporting.results import source_manifest, test_results


def main():
    project = Path(__file__).resolve().parents[1]
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    evidence = project / "reports" / stamp
    evidence.mkdir(parents=True)
    work_dir = project.parent / "codex" / "qa" / ("zhijing-report-" + stamp)
    work_dir.mkdir(parents=True)
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    checks = []

    def execute(name, arguments, filename):
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, *arguments],
            cwd=project,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        (evidence / filename).write_text(result.stdout, "utf-8")
        checks.append(
            {
                "name": name,
                "command": [sys.executable, *arguments],
                "exit_code": result.returncode,
                "seconds": round(time.perf_counter() - started, 4),
                "log": str((evidence / filename).relative_to(project)),
            }
        )

    execute(
        "pytest 全量测试",
        [
            "-m",
            "pytest",
            "-v",
            f"--junitxml={evidence / 'pytest.xml'}",
            f"--basetemp={work_dir / 'pytest'}",
            "-o",
            f"cache_dir={project.parent / 'codex/cache/zhijing-pytest'}",
        ],
        "pytest.log",
    )
    cache = str(project.parent / "codex/cache/zhijing-ruff")
    execute(
        "Ruff 代码检查",
        ["-m", "ruff", "check", "main.py", "src", "tests", "scripts", "--cache-dir", cache],
        "ruff-check.log",
    )
    execute(
        "Ruff 格式检查",
        [
            "-m",
            "ruff",
            "format",
            "--check",
            "main.py",
            "src",
            "tests",
            "scripts",
            "--cache-dir",
            cache,
        ],
        "ruff-format.log",
    )
    execute("正式入口环境自检", ["main.py", "--check"], "entry-check.json")
    tests = test_results(evidence / "pytest.xml", project / "scripts/reporting/case_catalog.json")
    http_cases = run_http(project, evidence, work_dir, sys.executable)
    report = {
        "timestamp": now.isoformat(timespec="seconds"),
        "evidence": str(evidence.relative_to(project)),
        "environment": {
            "Python": platform.python_version(),
            "解释器": sys.executable,
            "系统": platform.platform(),
            "数据模式": "extractive；独立临时数据库",
            **{
                name: version(name)
                for name in ["fastapi", "uvicorn", "pydantic", "httpx", "pytest", "ruff", "genanki"]
            },
        },
        "checks": checks,
        "tests": tests,
        "http": http_cases,
        "success": all(c["exit_code"] == 0 for c in checks)
        and bool(tests)
        and all(c["status"] == "通过" for c in tests + http_cases),
    }
    for name, data in [
        ("summary.json", report),
        ("http-results.json", http_cases),
        ("source-sha256.json", source_manifest(project)),
    ]:
        (evidence / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    write_reports(project, report)
    print(
        json.dumps(
            {
                "success": report["success"],
                "tests": len(tests),
                "http_cases": len(http_cases),
                "evidence": str(evidence),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
