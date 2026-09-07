import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from zhijing import browser, cli, startup

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_entry_rejects_invalid_ports(value):
    with pytest.raises(SystemExit) as exc:
        cli.create_parser().parse_args(["--port", value])
    assert exc.value.code == 2


def test_check_from_another_directory_does_not_create_database(tmp_path):
    data_dir = tmp_path / "unused-data"
    environment = {
        **os.environ,
        "ZHIJING_DATA_DIR": str(data_dir),
        "ZHIJING_MODEL_PROVIDER": "extractive",
    }
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--check"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ready"] is True
    assert Path(report["project_root"]) == PROJECT_ROOT
    assert set(report["dependencies"]) == set(startup.DEPENDENCIES)
    assert not data_dir.exists()


def test_check_reports_missing_dependency(monkeypatch):
    original_import = startup.importlib.import_module

    def import_without_genanki(name):
        if name == "genanki":
            raise ModuleNotFoundError("No module named 'genanki'")
        return original_import(name)

    monkeypatch.setattr(startup.importlib, "import_module", import_without_genanki)
    report = startup.check_environment()
    assert report["ready"] is False
    assert any("Dependency unavailable: genanki" in error for error in report["errors"])


def test_check_rejects_invalid_model_provider(monkeypatch, capsys):
    monkeypatch.setenv("ZHIJING_MODEL_PROVIDER", "unsupported")
    assert cli.main(["--check"]) == 2
    assert "ZHIJING_MODEL_PROVIDER" in json.loads(capsys.readouterr().out)["errors"][0]


def test_relative_data_path_is_anchored_to_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZHIJING_DATA_DIR", "local-data")
    report = startup.check_environment()
    assert Path(report["data_dir"]) == PROJECT_ROOT / "local-data"
    assert not (tmp_path / "local-data").exists()


def test_server_uses_requested_port_and_loopback(monkeypatch):
    import uvicorn

    created = []

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.started = False
            created.append(self)

        def run(self):
            self.started = True

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setenv("ZHIJING_MODEL_PROVIDER", "extractive")
    assert cli.main(["--port", "8765"]) == 0
    assert created[0].config.host == "127.0.0.1"
    assert created[0].config.port == 8765
    assert created[0].config.factory is True
    assert created[0].config.app == "zhijing.app:create_app"


def test_failed_preflight_does_not_start_server(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "check_environment", lambda: {"ready": False, "errors": ["Missing dependency"]}
    )
    assert cli.main([]) == 2
    assert "Missing dependency" in capsys.readouterr().err


@pytest.mark.parametrize(
    "started,health,expected",
    [(False, "ok", []), (True, "failed", []), (True, "ok", ["http://127.0.0.1:8765/"])],
)
def test_browser_waits_for_own_healthy_server(monkeypatch, started, health, expected):
    opened = []
    monkeypatch.setattr(browser.webbrowser, "open", opened.append)
    monkeypatch.setattr(
        browser,
        "build_opener",
        lambda *_: SimpleNamespace(
            open=lambda *_args, **_kwargs: BytesIO(json.dumps({"status": health}).encode())
        ),
    )

    class InlineThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(browser, "Thread", InlineThread)
    browser.open_docs_when_ready(
        SimpleNamespace(started=started),
        "http://127.0.0.1:8765",
        SimpleNamespace(wait=lambda _: False),
    )
    assert opened == expected
