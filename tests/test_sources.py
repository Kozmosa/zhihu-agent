import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings


def test_import_is_idempotent_and_persistent(tmp_path, sample):
    settings = Settings(data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/v1/sources/import", json=sample).json()
        assert client.post("/api/v1/sources/import", json=sample).json() == first
    with TestClient(create_app(settings)) as client:
        assert len(client.get("/api/v1/sources").json()) == 3
        assert client.get(f"/api/v1/sources/{first[0]['id']}").json() == first[0]


def test_author_filter_and_pagination(client, imported):
    rows = client.get("/api/v1/sources", params={"author_id": "demo-author-1"}).json()
    assert len(rows) == 2
    assert all(s["author_id"] == "demo-author-1" for s in rows)
    assert len(client.get("/api/v1/sources", params={"offset": 2, "limit": 1}).json()) == 1


@pytest.mark.parametrize(
    "field,value", [("text", "  "), ("url", "file:///etc/passwd"), ("title", "")]
)
def test_invalid_import(client, sample, field, value):
    sample["items"][0][field] = value
    assert client.post("/api/v1/sources/import", json=sample).status_code == 422
    assert client.get("/api/v1/sources").json() == []


def test_missing_source(client):
    response = client.get("/api/v1/sources/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "source_not_found"
