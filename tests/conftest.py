import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as test_client:
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
