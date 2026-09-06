import pytest


def test_direct_reading_keeps_leading_and_trailing_whitespace(client):
    text = "  \nAlpha paragraph.\n  "
    result = client.post("/api/v1/reading/analyze", json={"text": text}).json()
    assert "".join(section["text"] for section in result["sections"]) == text


def test_source_import_and_source_reading_keep_original_text(client, sample):
    text = "  \nAlpha paragraph.\n  "
    item = {**sample["items"][0], "text": text}
    response = client.post("/api/v1/sources/import", json={"items": [item]})
    assert response.status_code == 200
    source = response.json()[0]
    assert source["text"] == text
    result = client.post("/api/v1/reading/analyze", json={"source_id": source["id"]}).json()
    assert "".join(section["text"] for section in result["sections"]) == text


@pytest.mark.parametrize("text", ["", "  \n\t "])
def test_blank_source_text_still_rejected(client, sample, text):
    assert client.post("/api/v1/reading/analyze", json={"text": text}).status_code == 422
    item = {**sample["items"][0], "text": text}
    assert client.post("/api/v1/sources/import", json={"items": [item]}).status_code == 422
