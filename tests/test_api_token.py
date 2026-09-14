"""Opt-in API token: gates remote /api/v1 clients while local use stays unchanged."""

from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings

TOKEN = "unit-test-token-0123456789"


def remote_client(tmp_path, **settings):
    app = create_app(Settings(data_dir=tmp_path, **settings))
    return TestClient(app, client=("192.0.2.30", 12345))


def test_remote_business_api_requires_bearer_token(tmp_path):
    with remote_client(tmp_path, api_token=TOKEN) as client:
        rejected = client.get("/api/v1/runs")
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "invalid_api_token"
        assert rejected.headers["WWW-Authenticate"] == "Bearer"
        assert client.get("/api/v1/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert (
            client.get("/api/v1/runs", headers={"Authorization": f"Bearer {TOKEN}"}).status_code
            == 200
        )


def test_local_clients_settings_and_health_stay_open(tmp_path):
    with remote_client(tmp_path, api_token=TOKEN) as remote:
        assert remote.get("/health").status_code == 200
        # Settings endpoints keep their own local-only guard instead of the token.
        assert remote.get("/api/v1/settings/model").status_code == 403
    with TestClient(
        create_app(Settings(data_dir=tmp_path, api_token=TOKEN)), client=("127.0.0.1", 12345)
    ) as local:
        assert local.get("/api/v1/runs").status_code == 200
        assert local.get("/api/v1/settings/model").status_code == 200


def test_remote_access_stays_open_without_token(tmp_path):
    with remote_client(tmp_path) as client:
        assert client.get("/api/v1/runs").status_code == 200


def test_token_environment_is_validated_and_kept_private(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHIJING_API_TOKEN", TOKEN)
    settings = Settings.from_env()
    assert settings.api_token == TOKEN
    assert TOKEN not in repr(settings)
    assert not settings.validation_errors()
    weak = Settings(data_dir=tmp_path, api_token="short")
    assert any("ZHIJING_API_TOKEN" in error for error in weak.validation_errors())
