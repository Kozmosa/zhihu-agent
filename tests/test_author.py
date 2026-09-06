def test_retrieval_preserves_citations(client, imported):
    results = client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "主动回忆",
            "author_id": "demo-author-1",
        },
    ).json()
    assert results
    for item in results:
        source = client.get(f"/api/v1/sources/{item['source_id']}").json()
        assert item["excerpt"] in source["text"]
        assert item["author_id"] == "demo-author-1"


def test_primary_source_first_and_no_other_authors(client, imported):
    response = client.post(
        "/api/v1/author/ask",
        json={
            "author_id": "demo-author-1",
            "question": "主动回忆",
            "primary_source_id": imported[1]["id"],
        },
    )
    assert response.status_code == 200
    answer = response.json()
    assert answer["mode"] == "extractive"
    assert answer["citations"][0]["source_id"] == imported[1]["id"]
    assert all(c["author_id"] == "demo-author-1" for c in answer["citations"])


def test_wrong_author_rejected(client, imported):
    response = client.post(
        "/api/v1/author/ask",
        json={
            "author_id": "demo-author-2",
            "question": "阅读",
            "primary_source_id": imported[0]["id"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "author_mismatch"


def test_no_evidence_abstains(client, imported):
    result = client.post(
        "/api/v1/author/ask",
        json={
            "author_id": "unknown",
            "question": "量子引力",
        },
    ).json()
    assert result["citations"] == []
    assert "无法" in result["answer"]
