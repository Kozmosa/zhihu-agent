"""Host admission stays local-only unless extra hosts are explicitly configured."""

from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings


def test_public_host_is_rejected_by_default(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/health", headers={"host": "app.onrender.com"}).status_code == 400


def test_configured_hosts_admit_remote_clients_without_weakening_defaults(tmp_path):
    settings = Settings(data_dir=tmp_path, allowed_hosts=("app.onrender.com",))
    with TestClient(create_app(settings), client=("10.20.30.40", 55555)) as client:
        assert client.get("/health", headers={"host": "app.onrender.com"}).status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/health", headers={"host": "evil.example"}).status_code == 400


def test_allowed_hosts_environment_is_parsed_and_validated(monkeypatch):
    monkeypatch.setenv("ZHIJING_ALLOWED_HOSTS", " app.onrender.com , *.example.com ,, ")
    settings = Settings.from_env()
    assert settings.allowed_hosts == ("app.onrender.com", "*.example.com")
    assert not settings.validation_errors()
    assert Settings(allowed_hosts=("bad host",), data_dir=settings.data_dir).validation_errors()
