import json

import httpx
import pytest
from pydantic import Field

from zhijing.core.errors import DomainError
from zhijing.domain.models import Schema
from zhijing.infrastructure.ollama import OllamaGenerator


class Output(Schema):
    count: int = Field(ge=1)


@pytest.mark.parametrize("base", ["https://local", "https://local/api", "https://local/proxy/api"])
@pytest.mark.parametrize("format_name", ["schema", "json", "prompt"])
def test_structured_request_paths_formats_and_auth(base, format_name):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"response": '{"count": 2}', "done": True})

    with httpx.Client(
        base_url=base,
        headers={"Authorization": "Bearer test-only"},
        transport=httpx.MockTransport(handler),
    ) as client:
        result = OllamaGenerator(client, "test-model", output_format=format_name).generate(
            task="test",
            instructions="Count supplied items.",
            payload={"items": [1, 2]},
            response_model=Output,
        )
    request = requests[0]
    expected = "/proxy/api/generate" if "proxy" in base else "/api/generate"
    assert request.url.path == expected
    assert request.headers["authorization"] == "Bearer test-only"
    body = json.loads(request.content)
    prompt = json.loads(body["prompt"])
    assert body["model"] == "test-model" and body["stream"] is False
    assert body["options"]["num_ctx"] == 32768
    assert prompt["input"] == {"items": [1, 2]}
    assert prompt["schema"] == Output.model_json_schema()
    if format_name == "prompt":
        assert "format" not in body
    else:
        assert body["format"] == (prompt["schema"] if format_name == "schema" else "json")
    assert result.count == 2


@pytest.mark.parametrize(
    "envelope",
    [
        {"response": "not JSON"},
        {"response": '{"count": "2"}'},
        {"response": '{"count": 0}'},
        {"response": '{"count": 2, "extra": 3}'},
        {"response": '{"count": 2}', "done": False},
        {"response": '{"count": 2}', "done_reason": "length"},
        [],
        {"response": "x" * 256001},
    ],
)
def test_invalid_or_truncated_responses_are_not_downgraded(envelope):
    with httpx.Client(
        base_url="https://local",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope)),
    ) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model").generate(
                task="test", instructions="", payload={}, response_model=Output
            )
    assert error.value.code == "model_invalid_response" and error.value.status == 502


def test_input_budget_rejects_before_sending_or_truncating():
    calls = []
    with httpx.Client(
        base_url="https://local",
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    ) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model", max_input_chars=1000).generate(
                task="test", instructions="", payload={"text": "x" * 1001}, response_model=Output
            )
    assert error.value.status == 413 and calls == []


@pytest.mark.parametrize(
    "instructions,payload,options",
    [
        ("x" * 1001, {}, {"max_input_chars": 1000}),
        ("", {"text": "知" * 1000}, {"num_ctx": 4096, "num_predict": 1024}),
    ],
)
def test_budget_includes_system_text_and_conservative_token_reserve(instructions, payload, options):
    calls = []
    with httpx.Client(
        base_url="https://local",
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    ) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model", **options).generate(
                task="test", instructions=instructions, payload=payload, response_model=Output
            )
    assert error.value.status == 413 and calls == []


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_upstream_errors_do_not_expose_provider_body(status):
    with httpx.Client(
        base_url="https://local",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="secret-provider-details")
        ),
    ) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model").generate(
                task="test", instructions="", payload={}, response_model=Output
            )
    assert error.value.status == 502 and "secret-provider-details" not in str(error.value)


def test_timeout_is_explicit_and_not_retried():
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("private transport detail", request=request)

    with httpx.Client(base_url="https://local", transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model").generate(
                task="test", instructions="", payload={}, response_model=Output
            )
    assert error.value.code == "model_timeout" and len(calls) == 1


@pytest.mark.parametrize(
    "answer,citations",
    [("wrong [2]", [2]), ("mismatch [1]", [1, 1]), ("missing marker", [1]), ("extra [1][3]", [1])],
)
def test_author_rejects_untraceable_or_mismatched_references(answer, citations):
    from zhijing.domain.models import Citation

    envelope = {"response": json.dumps({"answer": answer, "citations": citations})}
    context = [
        Citation(
            source_id="s1",
            title="test",
            author_id="a1",
            url=None,
            chunk_index=0,
            excerpt="known text",
            score=1,
        )
    ]
    with httpx.Client(
        base_url="https://local",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=envelope)),
    ) as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model").answer("question", context)
    assert error.value.code == "model_invalid_response"
