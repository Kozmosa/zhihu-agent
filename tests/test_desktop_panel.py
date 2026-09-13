import subprocess
from pathlib import Path

import pytest

from zhijing import desktop_panel


class FakeEvents:
    instances = []

    def __init__(self, session, *, create):
        assert len(session) == 32
        assert create
        self.signals = []
        self.flags = set()
        self.closed = False
        self.instances.append(self)

    def set(self, name):
        self.signals.append(name)
        self.flags.add(name)

    def is_set(self, name):
        return name in self.flags

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *, hangs=False):
        self.returncode = None
        self.hangs = hangs
        self.terminated = False
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.hangs and not self.terminated:
            raise subprocess.TimeoutExpired("owned-panel", timeout)
        self.returncode = 0
        return 0

    def terminate(self):
        self.terminated = True


@pytest.fixture
def panel_fakes(monkeypatch):
    FakeEvents.instances = []
    calls = []

    def spawn(command, **kwargs):
        process = FakeProcess()
        calls.append((command, kwargs, process))
        return process

    monkeypatch.setattr(desktop_panel, "PanelEvents", FakeEvents)
    monkeypatch.setattr(desktop_panel.subprocess, "Popen", spawn)
    monkeypatch.setattr(desktop_panel.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(desktop_panel.sys, "frozen", False, raising=False)
    return calls


def test_launch_owns_one_child_and_commands_reuse_it(tmp_path, monkeypatch, panel_fakes):
    for name in ("ZHIHU_ACCESS_SECRET", "ZHIJING_OPENAI_API_KEY", "ZHIJING_OLLAMA_API_KEY"):
        monkeypatch.setenv(name, "synthetic-not-a-real-credential")
    controller = desktop_panel.PanelController(tmp_path, 12345)
    controller.hide()
    assert not panel_fakes
    controller.show()
    command, options, child = panel_fakes[0]
    assert command[:4] == [desktop_panel.sys.executable, "-s", "-B", str(tmp_path / "desktop.py")]
    assert command[command.index("--port") + 1] == "12345"
    assert command[command.index("--parent-pid") + 1] == str(desktop_panel.os.getpid())
    assert options["cwd"] == tmp_path
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert options["creationflags"] == 0x08000000
    assert options["env"]["PYTHONNOUSERSITE"] == "1"
    for name in ("ZHIHU_ACCESS_SECRET", "ZHIJING_OPENAI_API_KEY", "ZHIJING_OLLAMA_API_KEY"):
        assert name not in options["env"]
    events = controller.events
    events.flags.add("ready")
    controller.show()
    controller.hide()
    controller.toggle()
    assert len(panel_fakes) == 1
    assert events.signals == ["show", "hide", "toggle"]
    assert controller.poll_error() is None
    controller.shutdown()
    assert events.signals[-1] == "quit"
    assert events.closed and child.returncode == 0 and not child.terminated
    assert controller.process is controller.events is None
    controller.shutdown()


def test_unresponsive_child_is_terminated_without_touching_other_processes(tmp_path, panel_fakes):
    controller = desktop_panel.PanelController(tmp_path, 12345)
    controller.show()
    owned_child = controller.process
    owned_child.hangs = True
    unrelated_child = FakeProcess()
    controller.shutdown()
    assert owned_child.terminated
    assert owned_child.waits == [5, 3]
    assert unrelated_child.returncode is None and not unrelated_child.terminated
    assert FakeEvents.instances[0].closed


def test_failed_or_timed_out_child_reports_safe_error_and_can_restart(tmp_path, panel_fakes):
    controller = desktop_panel.PanelController(tmp_path, 12345)
    controller.show()
    controller.started_at -= 46
    message = controller.poll_error()
    assert "WebView2" in message
    assert controller.process is controller.events is None
    controller.toggle()
    assert len(panel_fakes) == 2
    controller.process.returncode = 2
    assert controller.poll_error() == message
    assert FakeEvents.instances[-1].closed


def test_launch_failure_releases_controls(tmp_path, monkeypatch, panel_fakes):
    def fail(*args, **kwargs):
        raise OSError("synthetic launch failure")

    monkeypatch.setattr(desktop_panel.subprocess, "Popen", fail)
    controller = desktop_panel.PanelController(tmp_path, 12345)
    with pytest.raises(OSError, match="synthetic launch failure"):
        controller.show()
    assert controller.process is controller.events is None
    assert FakeEvents.instances[0].closed


def test_frozen_launch_uses_executable_without_source_script(tmp_path, monkeypatch, panel_fakes):
    monkeypatch.setattr(desktop_panel.sys, "frozen", True)
    monkeypatch.setattr(desktop_panel.sys, "executable", str(tmp_path / "知境.exe"))
    controller = desktop_panel.PanelController(Path(tmp_path), 12346)
    controller.show()
    command = panel_fakes[0][0]
    assert command[:3] == [str(tmp_path / "知境.exe"), "--port", "12346"]
    assert "-s" not in command and "-B" not in command
    assert not any(argument.endswith("desktop.py") for argument in command)
    controller.shutdown()
