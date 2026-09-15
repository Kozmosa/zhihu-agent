import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings
from zhijing.local_auth import connect_local_client


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as test_client:
        connect_local_client(test_client)
        yield test_client


@pytest.fixture
def sample():
    path = Path(__file__).resolve().parents[1] / "examples" / "sources.json"
    return json.loads(path.read_text("utf-8"))


@pytest.fixture
def imported(client, sample):
    response = client.post("/api/v1/sources/import", json=sample)
    assert response.status_code == 200
    return response.json()
