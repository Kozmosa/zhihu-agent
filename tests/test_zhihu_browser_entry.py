"""Question-reading children dispatch before starting a mascot or local service."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def desktop_entry(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    path = Path(__file__).resolve().parents[1] / "desktop.py"
    spec = importlib.util.spec_from_file_location("_question_child_entry_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_question_worker_dispatches_without_creating_mascot(monkeypatch, tmp_path):
    calls = []
    module = desktop_entry(monkeypatch)
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setitem(
        sys.modules,
        "zhijing.zhihu_browser",
        SimpleNamespace(run_question_browser=lambda path: calls.append(path) or 7),
    )
    job = tmp_path / "question-job"
    monkeypatch.setattr(sys, "argv", ["desktop.py", "--zhihu-collect-job", str(job)])
    assert module.main() == 7
    assert calls == [job]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("extra", [["--check"], ["--desktop-panel", "other"], ["--parent-pid", "1"]])
def test_question_worker_cannot_mix_other_desktop_modes(monkeypatch, tmp_path, extra):
    module = desktop_entry(monkeypatch)
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "argv", ["desktop.py", "--zhihu-collect-job", str(tmp_path), *extra])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert not list(tmp_path.iterdir())
