import json

import pytest

from zhijing import cli
from zhijing.container import build_container
from zhijing.core.config import Settings


@pytest.mark.parametrize(
    "updates",
    [
        {"ollama_url": "file:///secret"},
        {"ollama_url": "https://user:secret@host"},
        {"ollama_url": "https://host?token=secret"},
        {"ollama_url": "http://host:bad"},
        {"ollama_timeout": float("nan")},
        {"ollama_timeout": 0},
        {"ollama_format": "unsupported"},
        {"ollama_max_input_chars": 0},
        {"ollama_num_predict": -1},
        {"ollama_api_key": "key\nheader"},
        {"ollama_model": " "},
        {"ollama_api_key": "非法测试key"},
        {"ollama_num_ctx": 2048},
        {"ollama_url": "https://host/api/generate"},
    ],
)
def test_bad_config_rejected_before_creating_database(tmp_path, updates):
    with pytest.raises(ValueError):
        build_container(Settings(data_dir=tmp_path / "data", **updates))
    assert not (tmp_path / "data").exists()


def test_key_not_in_settings_repr_or_preflight(monkeypatch, capsys):
    monkeypatch.setenv("ZHIJING_OLLAMA_API_KEY", "synthetic-test-secret")
    monkeypatch.setenv("ZHIJING_MODEL_PROVIDER", "ollama")
    assert "synthetic-test-secret" not in repr(Settings.from_env())
    assert cli.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "synthetic-test-secret" not in output
    assert json.loads(output)["model_provider"] == "ollama"


def test_non_numeric_config_gives_actionable_preflight(monkeypatch, capsys):
    monkeypatch.setenv("ZHIJING_OLLAMA_TIMEOUT", "not-a-number")
    assert cli.main(["--check"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["errors"] == ["ZHIJING_OLLAMA_TIMEOUT must be a valid number."]
