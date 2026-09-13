import json

import httpx
import pytest

from zhijing.core.errors import DomainError
from zhijing.domain.models import Citation
from zhijing.infrastructure.ollama import OllamaGenerator


def test_ollama_sends_only_supplied_evidence():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is False
        prompt = json.loads(body["prompt"])
        assert prompt["task"] == "author"
        assert prompt["input"]["evidence"][0]["text"] == "资料原文"
        assert body["format"] == prompt["schema"]
        answer = json.dumps({"answer": "根据资料[1]回答。", "citations": [1]})
        return httpx.Response(200, json={"response": answer, "done": True})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://ollama") as client:
        result = OllamaGenerator(client, "test-model").answer(
            "问题",
            [
                Citation(
                    source_id="1",
                    title="标题",
                    author_id="a",
                    url=None,
                    chunk_index=0,
                    excerpt="资料原文",
                    score=1,
                )
            ],
        )
    assert result.mode == "ollama"


@pytest.mark.parametrize(
    "status,payload", [(500, {}), (200, {}), (200, {"response": " "}), (200, {"response": []})]
)
def test_model_failures_are_explicit(status, payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
    with httpx.Client(transport=transport, base_url="https://ollama") as client:
        with pytest.raises(DomainError) as error:
            OllamaGenerator(client, "test-model").answer("问题", [])
    assert error.value.status == 502
