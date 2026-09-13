import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import zhijing.container as container_module
from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.infrastructure.ollama_transport import OllamaTransport
from zhijing.infrastructure.openai_compatible import OpenAICompatibleTransport
from zhijing.infrastructure.transcript_context import (
    TranscriptContext,
    reset_context,
    set_context,
)


def model_settings(provider, url, directory):
    return Settings(
        data_dir=directory,
        model_provider=provider,
        **{
            f"{provider}_url": url,
            f"{provider}_model": "fixture",
            f"{provider}_api_key": "synthetic-transport-audit-only",
        },
    )


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize(
    "url",
    [
        "http://model.example.test/v1",
        "http://localhost.evil.test/v1",
        "http://127.0.0.1.evil.test/v1",
        "http://192.168.1.20/v1",
        "http://10.0.0.2/v1",
        "http://[fe80::1]/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://[::1%25eth0]/v1",
        "http://2130706433/v1",
        "http://127.1/v1",
        "http://localhost./v1",
        "http://@localhost/v1",
        "https://user:synthetic@model.example.test/v1",
        "https://model.example.test/v1?key=synthetic",
        "https://model.example.test/v1#synthetic",
        "https://model.example.test/\\v1",
        "\x00https://model.example.test/v1",
    ],
)
def test_unsafe_model_urls_rejected_before_storage_or_client_creation(
    monkeypatch, tmp_path, provider, url
):
    def unexpected_client(**kwargs):
        pytest.fail("Invalid configuration must not initialize an HTTP client")

    monkeypatch.setattr(container_module, "httpx", SimpleNamespace(Client=unexpected_client))
    directory = tmp_path / "not-created"
    with pytest.raises(ValueError):
        container_module.build_container(model_settings(provider, url, directory))
    assert not directory.exists()


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize(
    "url",
    [
        "https://model.example.test/proxy/v1",
        "https://192.168.1.20/v1",
        "http://localhost:11434",
        "http://LOCALHOST:11434/api",
        "http://127.0.0.1:11434",
        "http://127.0.0.2:11434",
        "http://[::1]:11434",
    ],
)
def test_https_and_canonical_loopback_model_urls_remain_supported(provider, url):
    assert model_settings(provider, url, Path("unused-no-write")).validation_errors() == []


@pytest.mark.parametrize("provider", ["ollama", "openai"])
def test_model_container_explicitly_verifies_tls_and_disables_redirects(
    monkeypatch, tmp_path, provider
):
    real_client = httpx.Client
    client_options = []

    def make_client(**kwargs):
        client_options.append(kwargs)
        return real_client(
            **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
        )

    monkeypatch.setattr(container_module, "httpx", SimpleNamespace(Client=make_client))
    container = container_module.build_container(
        model_settings(provider, "https://model.example.test/v1", tmp_path)
    )
    try:
        model_options = next(item for item in client_options if "base_url" in item)
        assert model_options["verify"] is True
        assert model_options["follow_redirects"] is False
        assert model_options["trust_env"] is False
    finally:
        container.close()


def transport(provider, client, model="fixture"):
    if provider == "ollama":
        return OllamaTransport(client, model)
    return OpenAICompatibleTransport(client, model, 4096, 32768)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_model_transport_never_follows_redirect_even_with_permissive_client(provider, status):
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "http://collector.example.test/key"})

    with httpx.Client(
        base_url="https://model.example.test/v1",
        headers={"Authorization": "Bearer synthetic-transport-audit-only"},
        follow_redirects=True,
        transport=httpx.MockTransport(redirect),
    ) as client:
        with pytest.raises(DomainError) as error:
            transport(provider, client).request(
                prompt="fixture", instructions="", output_format=None
            )
    assert error.value.code == "model_unavailable"
    assert len(requests) == 1
    assert requests[0].url.host == "model.example.test"
    assert "synthetic-transport-audit-only" not in str(error.value)


@pytest.mark.parametrize("provider", ["ollama", "openai"])
@pytest.mark.parametrize("key", ["synthetic-transport-audit-only", 'synthetic-quote"slash\\key'])
def test_provider_reflected_credentials_are_rejected_without_response_transcript(provider, key):
    events = []
    context = TranscriptContext(
        SimpleNamespace(append=lambda **event: events.append(event)), "s", "r", "step"
    )

    def reflect_authorization(request):
        envelope = (
            {"response": '{"status":"ok"}', "done": True}
            if provider == "ollama"
            else {"choices": [{"message": {"content": '{"status":"ok"}'}, "finish_reason": "stop"}]}
        )
        envelope["debug"] = {"authorization": request.headers["Authorization"]}
        return httpx.Response(200, json=envelope)

    context_token = set_context(context)
    try:
        with httpx.Client(
            base_url="https://model.example.test/v1",
            headers={"Authorization": "Bearer " + key},
            transport=httpx.MockTransport(reflect_authorization),
        ) as client:
            with pytest.raises(DomainError) as error:
                transport(provider, client, model="fixture-" + key).request(
                    prompt=json.dumps({"accidental_key": key, "text": "normal diagnostic"}),
                    instructions="example " + key,
                    output_format=None,
                )
    finally:
        reset_context(context_token)
    assert error.value.code == "model_invalid_response"
    assert key not in str(error.value)
    assert [event["event"] for event in events] == ["request"]
    assert all(event["model"] == "fixture-[redacted]" for event in events)
    assert json.loads(events[0]["payload"]["prompt"]) == {
        "accidental_key": "[redacted]",
        "text": "normal diagnostic",
    }
    assert events[0]["payload"]["instructions"] == "example [redacted]"
    assert "normal diagnostic" in events[0]["payload"]["prompt"]
