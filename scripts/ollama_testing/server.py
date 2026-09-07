"""Start the formal entry in isolation and stop only the process created here."""

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

import httpx


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def application(project, work, ollama_url, model, timeout, mock):
    port = free_port()
    # Windows may expose both Path and PATH in an inherited environment.
    environment = {key.upper(): value for key, value in os.environ.items()}
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "ZHIJING_DATA_DIR": str(work / "data"),
            "ZHIJING_MODEL_PROVIDER": "ollama",
            "ZHIJING_OLLAMA_URL": ollama_url,
            "ZHIJING_OLLAMA_MODEL": model,
            "ZHIJING_OLLAMA_TIMEOUT": str(timeout),
        }
    )
    if mock:
        environment.pop("ZHIJING_OLLAMA_API_KEY", None)
        environment["ZHIJING_OLLAMA_FORMAT"] = "schema"
    command = [sys.executable, str(project / "main.py"), "--port", str(port)]
    with (work / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=work,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=timeout, trust_env=False
            ) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Formal entry exited: {process.returncode}")
                    try:
                        if client.get("/health", timeout=0.5).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise TimeoutError("Formal entry did not become healthy in 20 seconds")
                yield client
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
