from types import SimpleNamespace

import httpx
import pytest

from zhijing.core.config import Settings
from zhijing.runtime import Runtime


def test_startup_recovery_failure_releases_created_model_client(tmp_path, monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    def fail_recovery():
        raise OSError("synthetic unavailable run store")

    container = SimpleNamespace(
        runs=SimpleNamespace(recover_interrupted=fail_recovery), close=client.close
    )
    monkeypatch.setattr("zhijing.runtime.build_container", lambda settings: container)
    with pytest.raises(OSError):
        Runtime(Settings(data_dir=tmp_path))
    assert client.is_closed
