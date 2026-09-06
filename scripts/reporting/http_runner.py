"""以真实进程从项目外启动正式入口，测试结束只停止本次子进程。"""

import json
import os
import socket
import subprocess
import time

import httpx

from reporting.http_cases import exercise


def run_http(project, evidence, work_dir, python):
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    environment = os.environ.copy()
    environment.update(
        {
            "ZHIJING_DATA_DIR": str(work_dir / "http-data"),
            "ZHIJING_MODEL_PROVIDER": "extractive",
            "PYTHONUTF8": "1",
        }
    )
    command = [python, str(project / "main.py"), "--port", str(port)]
    started = time.perf_counter()
    cases = []
    with (evidence / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=work_dir, env=environment, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False
            ) as client:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError(f"启动进程提前退出，exit={process.returncode}")
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise TimeoutError("15 秒内服务未就绪")
                cases.append(
                    {
                        "title": "正式入口从项目外启动",
                        "input": "main.py --port，工作目录为独立 QA 目录",
                        "expected": "15 秒内健康接口可用",
                        "actual": {
                            "port": port,
                            "working_directory": str(work_dir),
                            "pid": process.pid,
                        },
                        "status": "通过",
                        "seconds": round(time.perf_counter() - started, 4),
                    }
                )
                sample = json.loads((project / "examples" / "sources.json").read_text("utf-8"))
                cases.extend(exercise(client, sample))
        except Exception as error:
            cases.append(
                {
                    "title": "正式入口启动",
                    "input": command,
                    "expected": "服务可用",
                    "actual": str(error),
                    "status": "失败",
                    "seconds": round(time.perf_counter() - started, 4),
                }
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    return cases
