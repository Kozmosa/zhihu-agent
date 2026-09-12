import importlib.util
import sys
from pathlib import Path

from zhijing.desktop_service import DesktopService, default_data_directory


def test_frozen_defaults_use_local_app_data_and_preserve_override_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.delenv("ZHIJING_DATA_DIR", raising=False)
    application = tmp_path / "read-only-application"
    expected = tmp_path / "local-app-data" / "ZhiJing" / "data"
    assert default_data_directory(application) == expected
    assert DesktopService(application).data_dir == expected

    monkeypatch.setenv("ZHIJING_DATA_DIR", "relative-user-data")
    relative = tmp_path / "local-app-data" / "ZhiJing" / "relative-user-data"
    assert default_data_directory(application) == relative
    assert DesktopService(application).data_dir == relative
    explicit = tmp_path / "explicit-data"
    assert DesktopService(application, data_dir=explicit).data_dir == explicit
    assert not any(tmp_path.iterdir()), "Path selection must not create or read a database"


def test_frozen_entry_uses_executable_directory_instead_of_unpack_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    executable = tmp_path / "application" / "知境.exe"
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "unpacked-resources"), raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.delenv("ZHIJING_DATA_DIR", raising=False)
    entry = Path(__file__).resolve().parents[1] / "desktop.py"
    specification = importlib.util.spec_from_file_location("_desktop_frozen_test_entry", entry)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    assert module.PROJECT_ROOT == executable.parent
    assert not any(tmp_path.iterdir()), "Importing the frozen entry must not start UI or storage"
