import json
import os
import traceback

import httpx
import pytest

from zhijing.core import credentials
from zhijing.core.config import Settings, model_profile
from zhijing.core.errors import DomainError
from zhijing.infrastructure.ollama_transport import OllamaTransport
from zhijing.infrastructure.openai_compatible import OpenAICompatibleTransport
from zhijing.infrastructure.sqlite_transcript import SQLiteTranscript
from zhijing.infrastructure.transcript_context import TranscriptContext, reset_context, set_context

KEY = "synthetic-key-for-protection-only"


class MemoryProtector:
    """An injected opaque store; production always uses Windows DPAPI."""

    def __init__(self):
        self.values = {}

    def protect(self, value):
        opaque = os.urandom(32)
        self.values[opaque] = value
        return opaque

    def unprotect(self, value):
        return self.values[value]


@pytest.fixture
def protected(monkeypatch):
    protector = MemoryProtector()
    monkeypatch.setattr(credentials, "default_protector", lambda: protector)
    return protector


def profile():
    return model_profile(Settings(data_dir=None, model_provider="openai", openai_api_key=KEY))


def test_ciphertext_only_roundtrip_and_restart(tmp_path, protected, monkeypatch):
    credentials.save_model_profile(tmp_path, profile())
    assert [path.name for path in tmp_path.iterdir()] == [credentials.PROFILE_FILE]
    assert KEY.encode() not in (tmp_path / credentials.PROFILE_FILE).read_bytes()
    for name in list(os.environ):
        if (
            name.startswith(("ZHIJING_OPENAI_", "ZHIJING_OLLAMA_"))
            or name == "ZHIJING_MODEL_PROVIDER"
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(tmp_path))
    loaded = Settings.from_env()
    assert loaded.openai_api_key == KEY
    assert loaded.model_config_persistence == "encrypted_local"
    assert KEY not in repr(loaded)


def test_legacy_migration_verifies_and_leaves_no_plaintext_copy(tmp_path, protected):
    legacy = tmp_path / credentials.LEGACY_FILE
    legacy.write_text(json.dumps(profile()))
    assert credentials.migrate_legacy_model_profile(tmp_path)
    assert not legacy.exists()
    assert credentials.load_protected_profile(tmp_path) == profile()
    assert all(KEY.encode() not in path.read_bytes() for path in tmp_path.iterdir())
    assert not credentials.migrate_legacy_model_profile(tmp_path)


def test_migration_failure_preserves_original_without_new_plaintext_backup(tmp_path, monkeypatch):
    legacy = tmp_path / credentials.LEGACY_FILE
    legacy.write_text(json.dumps(profile()))

    class Unavailable(MemoryProtector):
        def protect(self, value):
            raise credentials.CredentialStorageError("Cannot protect fixture")

    monkeypatch.setattr(credentials, "default_protector", Unavailable)
    with pytest.raises(credentials.CredentialStorageError):
        credentials.migrate_legacy_model_profile(tmp_path)
    assert json.loads(legacy.read_text()) == profile()
    assert [p.name for p in tmp_path.iterdir()] == [credentials.LEGACY_FILE]


def test_conflicting_legacy_never_overwrites_encrypted_profile(tmp_path, protected):
    credentials.save_model_profile(tmp_path, profile())
    legacy = tmp_path / credentials.LEGACY_FILE
    legacy.write_text(json.dumps({"ZHIJING_MODEL_PROVIDER": "extractive"}))
    with pytest.raises(credentials.CredentialStorageError, match="不一致"):
        credentials.migrate_legacy_model_profile(tmp_path)
    assert legacy.exists()
    assert credentials.load_protected_profile(tmp_path) == profile()


def test_non_windows_protection_fails_without_plaintext_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials.os, "name", "posix")
    with pytest.raises(credentials.CredentialStorageError, match="Windows"):
        credentials.WindowsDPAPI().protect(KEY.encode())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_windows_dpapi_real_encryption_roundtrip(tmp_path):
    credentials.save_model_profile(tmp_path, profile())
    assert KEY.encode() not in (tmp_path / credentials.PROFILE_FILE).read_bytes()
    assert credentials.load_protected_profile(tmp_path) == profile()


@pytest.mark.parametrize(
    "url", ["http://model.example/v1", "http://127.0.0.1.evil.test/v1", "http://10.0.0.1/v1"]
)
def test_remote_bearer_requires_https(tmp_path, url):
    errors = Settings(
        data_dir=tmp_path, model_provider="openai", openai_url=url, openai_api_key=KEY
    ).validation_errors()
    assert any("HTTPS" in error for error in errors)
    assert KEY not in str(errors)


@pytest.mark.parametrize(
    "url",
    [
        "https://model.example/v1",
        "http://localhost:8080/v1",
        "http://127.0.0.1/v1",
        "http://[::1]/v1",
    ],
)
def test_tls_or_loopback_is_accepted(tmp_path, url):
    assert not Settings(
        data_dir=tmp_path, model_provider="openai", openai_url=url, openai_api_key=KEY
    ).validation_errors()


@pytest.mark.parametrize("provider", ["openai", "ollama"])
@pytest.mark.parametrize("kind", ["echo", "escaped_echo", "error", "redirect"])
def test_provider_cannot_return_or_record_key(tmp_path, provider, kind):
    calls = []

    def handle(request):
        calls.append(request)
        if kind == "error":
            return httpx.Response(500, text=KEY)
        if kind == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.example/" + KEY})
        result = json.dumps({"answer": KEY})
        if kind == "escaped_echo":
            result = '{"answer":"' + "".join(f"\\u{ord(c):04x}" for c in KEY) + '"}'
        return httpx.Response(
            200,
            json=(
                {"choices": [{"message": {"content": result}, "finish_reason": "stop"}]}
                if provider == "openai"
                else {"response": result, "done": True}
            ),
        )

    transcript = SQLiteTranscript(tmp_path / "trace.db", secrets=(KEY,))
    transcript.initialize()
    token = set_context(TranscriptContext(transcript, "s", "r", "reading"))
    try:
        with httpx.Client(
            base_url="https://model.example",
            headers={"Authorization": "Bearer " + KEY},
            follow_redirects=True,
            transport=httpx.MockTransport(handle),
        ) as client:
            transport = (
                OpenAICompatibleTransport(client, "fixture", 4096, 32768)
                if provider == "openai"
                else OllamaTransport(client, "fixture")
            )
            with pytest.raises(DomainError) as caught:
                transport.request(prompt="normal", instructions="test", output_format="json")
            assert KEY not in "".join(traceback.format_exception(caught.value))
    finally:
        reset_context(token)
    assert len(calls) == 1
    assert KEY not in json.dumps(transcript.list("r"))
    assert KEY.encode() not in transcript.path.read_bytes()
    assert [event["event"] for event in transcript.list("r")] == ["request"]


def test_accidental_key_in_prompt_is_redacted_before_sending_and_recording(tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"response": '{"count":2}', "done": True})

    with httpx.Client(
        base_url="https://model.example",
        headers={"Authorization": "Bearer " + KEY},
        transport=httpx.MockTransport(handle),
    ) as client:
        result = OllamaTransport(client, "fixture").request(
            prompt=KEY, instructions=KEY, output_format="json"
        )
    assert result == '{"count":2}'
    assert KEY.encode() not in requests[0].content
    assert requests[0].headers["authorization"] == "Bearer " + KEY


def test_direct_transcript_nested_values_redact(tmp_path):
    transcript = SQLiteTranscript(tmp_path / "trace.db", secrets=(KEY,))
    transcript.initialize()
    transcript.append(run_id="r", model=KEY, payload={KEY: [{"nested": KEY}]})
    assert KEY not in json.dumps(transcript.list("r"))
    assert KEY.encode() not in transcript.path.read_bytes()
