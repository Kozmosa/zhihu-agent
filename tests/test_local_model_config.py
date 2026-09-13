import json
import os

import pytest

from zhijing.core.config import Settings


@pytest.fixture
def local(tmp_path, monkeypatch):
    for key in list(os.environ):
        if (
            key.startswith(("ZHIJING_OPENAI_", "ZHIJING_OLLAMA_"))
            or key == "ZHIJING_MODEL_PROVIDER"
        ):
            monkeypatch.delenv(key)
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(tmp_path))
    return tmp_path / "model-config.json"


def test_load_saved_profile_without_mutating_environment(local):
    local.write_text(
        json.dumps({"ZHIJING_MODEL_PROVIDER": "openai", "ZHIJING_OPENAI_API_KEY": "test-secret"})
    )
    s = Settings.from_env()
    assert s.model_provider == "openai"
    assert s.openai_model == "deepseek-v4-flash"
    assert s.openai_api_key == "test-secret"
    assert not s.validation_errors()
    assert "test-secret" not in repr(s)
    assert "ZHIJING_OPENAI_API_KEY" not in os.environ


def test_endpoint_override_does_not_reuse_saved_key(local, monkeypatch):
    local.write_text(
        json.dumps({"ZHIJING_MODEL_PROVIDER": "openai", "ZHIJING_OPENAI_API_KEY": "test-secret"})
    )
    monkeypatch.setenv("ZHIJING_OPENAI_URL", "https://example.org/v1")
    s = Settings.from_env()
    assert s.openai_api_key == ""
    assert s.openai_url == "https://example.org/v1"


def test_missing_profile_stays_offline(local):
    assert Settings.from_env().model_provider == "extractive"


@pytest.mark.parametrize(
    "value",
    ['["secret"]', '{"unexpected":"secret"}', '{"ZHIJING_OPENAI_API_KEY":42}', "secret-not-json"],
)
def test_invalid_file_redacts_contents(local, value):
    local.write_text(value)
    with pytest.raises(ValueError, match="Local model-config.json") as e:
        Settings.from_env()
    assert "secret" not in str(e.value)
