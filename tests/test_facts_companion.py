def test_fact_review_never_equates_mention_with_truth(client, imported):
    result = client.post(
        "/api/v1/facts/review",
        json={
            "claims": [
                "主动回忆是尝试在不看原文的情况下回想所学内容。",
                "主动回忆完全没有效果。",
                "zyxwv987654",
            ]
        },
    ).json()
    assert [r["status"] for r in result["reviews"]] == [
        "mentioned_in_corpus",
        "related_evidence",
        "insufficient_evidence",
    ]
    assert "尚未验证真实性" in result["reviews"][0]["explanation"]


def test_companion_integrates_all_features_and_excludes_self(client, imported):
    source_id = imported[0]["id"]
    response = client.post(
        "/api/v1/companion/run",
        json={
            "source_id": source_id,
            "tasks": ["reading", "cards", "facts", "author"],
            "question": "主动回忆",
            "claims": ["主动回忆是尝试在不看原文的情况下回想所学内容。"],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["reading"]["sections"]
    assert result["cards"]["cards"]
    assert result["author"]["citations"][0]["source_id"] == source_id
    evidence = result["facts"]["reviews"][0]["evidence"]
    assert evidence and all(c["source_id"] != source_id for c in evidence)


def test_companion_requires_explicit_claims(client, imported):
    response = client.post(
        "/api/v1/companion/run", json={"source_id": imported[0]["id"], "tasks": ["facts"]}
    )
    assert response.status_code == 422


def test_health_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert "/api/v1/companion/run" in schema["paths"]
