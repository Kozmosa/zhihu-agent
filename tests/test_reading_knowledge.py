import pytest

from zhijing.core.text import chunks


def test_long_unpunctuated_text_is_bounded():
    text = "长" * 4100
    parts = chunks(text, 600)
    assert "".join(parts) == text
    assert max(map(len, parts)) <= 600


def test_reader_preserves_content(client, imported):
    source = imported[0]
    response = client.post(
        "/api/v1/reading/analyze", json={"source_id": source["id"], "chunk_size": 100}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "extractive"
    assert "".join(s["text"] for s in data["sections"]) == source["text"]
    assert all(len(s["text"]) <= 100 for s in data["sections"])


@pytest.mark.parametrize(
    "body", [{}, {"text": "x", "source_id": "x"}, {"text": "  "}, {"text": "a", "chunk_size": 0}]
)
def test_reader_input_contract(client, body):
    assert client.post("/api/v1/reading/analyze", json=body).status_code == 422


def test_xyflow_graph_has_valid_edges(client, imported):
    data = client.get("/api/v1/knowledge-map").json()
    ids = [n["id"] for n in data["nodes"]]
    assert len(ids) == len(set(ids))
    assert all(e["source"] in ids and e["target"] in ids for e in data["edges"])
    assert sum(n["data"]["kind"] == "answer" for n in data["nodes"]) == 3
    limited = client.get("/api/v1/knowledge-map?limit=1").json()
    assert limited["truncated"] is True
    assert limited["total_sources"] == 3
