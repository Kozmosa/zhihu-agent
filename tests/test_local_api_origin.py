import pytest


@pytest.mark.parametrize("origin", ["https://example.org", "null", "http://testserver:9999"])
def test_foreign_origin_cannot_read_or_call_local_api(client, origin):
    for method, path, body in [
        ("get", "/api/v1/sources", None),
        ("post", "/api/v1/reading/analyze", {"text": "testing"}),
    ]:
        response = client.request(method, path, json=body, headers={"Origin": origin})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "invalid_origin"
        assert response.headers["cache-control"] == "no-store"


def test_cross_site_fetch_metadata_blocked_even_without_origin(client):
    response = client.get("/api/v1/knowledge-map", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_same_origin_and_local_scripts_continue(client):
    for headers in ({}, {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}):
        response = client.get("/api/v1/sources", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
