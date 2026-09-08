import json

import httpx
import pytest

from zhijing.core.config import Settings
from zhijing.core.errors import DomainError
from zhijing.features.reader.generation import GeneratedReading
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator
from zhijing.settings_ui import ModelConfiguration


@pytest.mark.parametrize("generator_type", [OllamaGenerator, OpenAICompatibleGenerator])
def test_budget_preflight_rejects_before_network_and_matches_generation(generator_type):
    calls = []
    with httpx.Client(
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    ) as client:
        generator = generator_type(client, "fixture", num_ctx=4096)
        arguments = dict(
            task="reading",
            instructions="JSON",
            payload={"text": "字" * 10000},
            response_model=GeneratedReading,
        )
        for method in [generator.check_budget, generator.generate]:
            with pytest.raises(DomainError) as error:
                method(**arguments)
            assert error.value.code == "model_input_too_large"
        assert calls == []


@pytest.mark.parametrize("thinking", ["auto", "disabled", "enabled"])
def test_compatible_thinking_is_optional_and_reasoning_is_not_result(thinking):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"summary":"ok","sections":[]}',
                            "reasoning_content": "private-provider-reasoning",
                        },
                    }
                ]
            },
        )

    with httpx.Client(
        base_url="https://example.invalid/v1", transport=httpx.MockTransport(respond)
    ) as client:
        generator = OpenAICompatibleGenerator(client, "fixture", thinking=thinking)
        text = generator.transport.request(prompt="JSON", instructions="JSON", output_format="json")
    assert "private-provider-reasoning" not in text
    assert requests[0]["response_format"] == {"type": "json_object"}
    if thinking == "auto":
        assert "thinking" not in requests[0]
    else:
        assert requests[0]["thinking"] == {"type": thinking}


def test_thinking_config_and_environment_are_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJING_OPENAI_THINKING", "disabled")
    assert Settings.from_env().openai_thinking == "disabled"
    base = Settings(data_dir=tmp_path)
    config = ModelConfiguration(
        provider="openai",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        thinking="disabled",
    )
    assert config.settings(base).openai_thinking == "disabled"
    assert Settings(
        data_dir=tmp_path,
        model_provider="openai",
        openai_model="fixture",
        openai_thinking="invalid",
    ).validation_errors()
