"""Local .env loading: precedence, parsing and startup integration."""

import os

import pytest

from zhijing import startup


@pytest.fixture(autouse=True)
def _restore_process_environment():
    # setdefault-inserted keys are not covered by monkeypatch when the key was absent.
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


def test_local_env_supplements_but_never_overrides_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJING_MODEL_PROVIDER", "extractive")
    monkeypatch.delenv("ZHIJING_OPENAI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ZHIJING_MODEL_PROVIDER=openai\nZHIJING_OPENAI_API_KEY="sk-test"\n',
        encoding="utf-8",
    )
    assert startup.load_local_env(env_file) == env_file
    assert os.environ["ZHIJING_MODEL_PROVIDER"] == "extractive"
    assert os.environ["ZHIJING_OPENAI_API_KEY"] == "sk-test"


def test_local_env_parses_quotes_and_skips_comments_and_malformed_lines(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n"
        "# comment=ignored\n"
        "export ZHIJING_OLLAMA_MODEL=qwen3:8b\n"
        "ZHIHU_ACCESS_SECRET='abc=def'\n"
        "1INVALID=nope\n"
        "NO_EQUALS_SIGN\n",
        encoding="utf-8",
    )
    for key in ("ZHIJING_OLLAMA_MODEL", "ZHIHU_ACCESS_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert startup.load_local_env(env_file) == env_file
    assert os.environ["ZHIJING_OLLAMA_MODEL"] == "qwen3:8b"
    assert os.environ["ZHIHU_ACCESS_SECRET"] == "abc=def"


def test_local_env_without_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHIJING_OPENAI_MODEL", raising=False)
    assert startup.load_local_env(tmp_path / ".env") is None
    assert "ZHIJING_OPENAI_MODEL" not in os.environ


def test_local_env_skips_frozen_builds(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ZHIJING_OLLAMA_MODEL=frozen-value\n", encoding="utf-8")
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.delenv("ZHIJING_OLLAMA_MODEL", raising=False)
    assert startup.load_local_env(env_file) is None
    assert "ZHIJING_OLLAMA_MODEL" not in os.environ


def test_check_environment_reads_project_local_env_before_resolving_paths(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "ZHIJING_DATA_DIR=state\nZHIJING_MODEL_PROVIDER=openai\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(startup, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ZHIJING_DATA_DIR", raising=False)
    monkeypatch.delenv("ZHIJING_MODEL_PROVIDER", raising=False)
    report = startup.check_environment()
    assert report["model_provider"] == "openai"
    assert report["data_dir"] == str((tmp_path / "state").resolve())
