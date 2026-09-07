"""Run Node UI handlers against an isolated local service; never touches user data."""

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

import httpx
import uvicorn

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from zhijing.app import create_app  # noqa: E402
from zhijing.core.config import Settings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-root", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    work = args.work_root or (
        project.parent
        / "codex"
        / "qa"
        / ("zhijing-workspace-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    )
    work.mkdir(parents=True, exist_ok=True)
    # Each invocation gets a fresh database so pagination and empty-library checks are meaningful.
    data = work / ("data-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings(data_dir=data)), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            for _ in range(100):
                if not thread.is_alive():
                    raise RuntimeError("Test service exited before startup")
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise TimeoutError("Test service did not become healthy")
        result = subprocess.run(
            [
                "node",
                str(project / "scripts" / "check_workspace_ui.cjs"),
                f"http://127.0.0.1:{port}",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        (work / "ui.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(
            json.dumps(
                {
                    "passed": result.returncode == 0,
                    "report": str(work / "ui.log"),
                    "scope": "DOM handlers and real HTTP; visual/browser QA not performed",
                }
            )
        )
        if result.returncode:
            print(result.stdout + result.stderr)
        return result.returncode
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("Test service did not shut down")


if __name__ == "__main__":
    raise SystemExit(main())
