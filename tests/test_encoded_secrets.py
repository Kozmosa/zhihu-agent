"""Credential boundaries exercised only with synthetic keys and mock HTTP."""

import json
from urllib.parse import quote

import httpx
import pytest

from zhijing.core.errors import DomainError
from zhijing.core.redaction import SecretRedactor
from zhijing.features.zhihu.service import ZhihuSearchService
from zhijing.infrastructure.ollama_transport import OllamaTransport
from zhijing.infrastructure.openai_compatible import OpenAICompatibleTransport
from zhijing.infrastructure.sqlite_transcript import SQLiteTranscript
from zhijing.infrastructure.transcript_context import TranscriptContext, reset_context, set_context
from zhijing.infrastructure.zhihu_search import ZhihuSearchClient

KEY = "synthetic-only-AuditKey+123/456"


def encoded(kind, value=KEY):
    if kind == "percent":
        return "".join(f"%{ord(char):02x}" for char in value)
    if kind == "unicode":
        return "".join(f"\\u{ord(char):04x}" for char in value)
    if kind == "html":
        return "".join(f"&#{ord(char)};" for char in value)
    if kind == "mixed":
        return "".join(
            encoded(("percent", "unicode", "html")[index % 3], char)
            for index, char in enumerate(value)
        )
    if kind == "nested":
        return quote(encoded("html", encoded("unicode", value)), safe="")
    raise AssertionError(kind)


ENCODINGS = ("percent", "unicode", "html", "mixed", "nested")


@pytest.mark.parametrize("kind", ENCODINGS)
def test_encoded_key_redacts_only_its_original_span(kind):
    redactor = SecretRedactor((KEY,))
    untouched = r"中文 %20 &amp; \u4e2d \n "
    value = untouched + encoded(kind) + " / " + encoded(kind) + untouched
    assert redactor.contains(value)
    assert redactor.text(value) == untouched + "[redacted] / [redacted]" + untouched
    assert redactor.text(untouched) == untouched
    assert not redactor.contains(untouched)


def test_malformed_escapes_and_large_numeric_entities_do_not_raise_or_rewrite():
    redactor = SecretRedactor((KEY,))
    value = "&#" + "9" * 10000 + r"; %GG \uZZZZ &unknown;"
    assert not redactor.contains(value)
    assert redactor.text(value) == value


def test_unknown_entity_keeps_unrelated_prefix_when_adjacent_escapes_form_a_key():
    redactor = SecretRedactor(("fixture-audit-key",))
    assert redactor.text("&fixture-audit-ke%79;") == "&[redacted];"


@pytest.mark.parametrize("provider", ("openai", "ollama"))
@pytest.mark.parametrize("kind", ENCODINGS)
def test_encoded_input_is_not_sent_or_saved(tmp_path, provider, kind):
    calls = []

    def handle(request):
        calls.append(request)
        payload = (
            {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}
            if provider == "openai"
            else {"response": '{"ok":true}', "done": True}
        )
        return httpx.Response(200, json=payload)

    transcript = SQLiteTranscript(tmp_path / "trace.db", secrets=(KEY,))
    transcript.initialize()
    context = set_context(TranscriptContext(transcript, "s", "r", "test"))
    untouched = r"preserve %20 &amp; \u4e2d"
    try:
        with httpx.Client(
            base_url="https://model.invalid",
            headers={"Authorization": "Bearer " + KEY},
            transport=httpx.MockTransport(handle),
        ) as client:
            transport = (
                OpenAICompatibleTransport(client, "fixture", 4096, 32768)
                if provider == "openai"
                else OllamaTransport(client, "fixture")
            )
            transport.request(
                prompt=untouched + encoded(kind),
                instructions=encoded(kind),
                output_format="json",
            )
    finally:
        reset_context(context)
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    prompt = body["messages"][1]["content"] if provider == "openai" else body["prompt"]
    assert prompt == untouched + "[redacted]"
    assert calls[0].headers["Authorization"] == "Bearer " + KEY
    events = transcript.list("r")
    assert events[0]["payload"] == {
        "prompt": untouched + "[redacted]",
        "instructions": "[redacted]",
    }
    assert not SecretRedactor((KEY,)).contains(json.dumps(events))
    assert encoded(kind).encode() not in transcript.path.read_bytes()
    assert KEY.encode() not in transcript.path.read_bytes()


@pytest.mark.parametrize("kind", ENCODINGS)
def test_direct_transcript_redacts_encoded_keys_and_values(tmp_path, kind):
    transcript = SQLiteTranscript(tmp_path / "trace.db", secrets=(KEY,))
    transcript.initialize()
    transcript.append(run_id="r", model=encoded(kind), payload={encoded(kind): encoded(kind)})
    event = transcript.list("r")[0]
    assert event["model"] == "[redacted]"
    assert event["payload"] == {"[redacted]": "[redacted]"}
    assert encoded(kind).encode() not in transcript.path.read_bytes()


@pytest.mark.parametrize("kind", ENCODINGS)
@pytest.mark.parametrize("field", ("model", "base_url"))
def test_api_rejects_encoded_credential_in_public_configuration(client, kind, field):
    config = {
        "provider": "openai",
        "api_key": KEY,
        "base_url": "https://model.invalid/v1",
        "model": "fixture",
    }
    config[field] = ("https://model.invalid/" if field == "base_url" else "") + encoded(kind)
    response = client.post("/api/v1/settings/model/apply", json=config)
    assert response.status_code == 422
    assert KEY not in response.text and encoded(kind) not in response.text
    status = client.get("/api/v1/settings/model")
    assert status.json()["provider"] == "extractive"
    assert not SecretRedactor((KEY,)).contains(status.text)


@pytest.mark.parametrize("representation", ("html", "mixed", "joined_tags"))
@pytest.mark.parametrize("field", ("ContentText", "Title", "AuthorName"))
def test_search_rejects_secret_after_html_cleaning(representation, field):
    safe = {
        "ContentID": "123",
        "ContentType": "answer",
        "Title": "正常资料",
        "ContentText": "保留原有中文资料。",
        "AuthorName": "测试作者",
        "Url": "https://www.zhihu.com/question/1/answer/123",
    }
    reflected = (
        KEY[:10] + "<em></em>" + KEY[10:]
        if representation == "joined_tags"
        else encoded(representation)
    )
    payload = {"Code": 0, "Data": {"Items": [{**safe, field: reflected}, safe]}}
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        result = ZhihuSearchService(ZhihuSearchClient(client, KEY)).search("正常查询", 2)
    assert len(result.items) == 1
    assert result.items[0].text == safe["ContentText"]
    assert result.skipped_count == 1
    assert not SecretRedactor((KEY,)).contains(result.model_dump_json())


@pytest.mark.parametrize("kind", ("plain", *ENCODINGS))
def test_search_rejects_secret_before_any_get_request(kind):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"Code": 0, "Data": {"Items": []}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        transport = ZhihuSearchClient(client, KEY)
        with pytest.raises(DomainError) as caught:
            transport.search("search " + (KEY if kind == "plain" else encoded(kind)), 1)
    assert not calls
    assert caught.value.code == "zhihu_sensitive_query"
    assert not SecretRedactor((KEY,)).contains(str(caught.value))
