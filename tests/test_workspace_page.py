import re

from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings


def test_workspace_assets_are_packaged_and_local_only(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        page = client.get("/workspace")
        assert page.status_code == 200
        assert "__CONFIG_TOKEN__" not in page.text
        assert 'src="/assets/workspace.js"' in page.text
        nonce = re.search(r"nonce-([^']+)", page.headers["content-security-policy"])[1]
        assert nonce != client.app.state.config_token
        assert f'nonce="{nonce}"' in page.text
        assert "style-src 'self'" in page.headers["content-security-policy"]
        for filename, content_type in [
            ("workspace.js", "text/javascript"),
            ("workspace.css", "text/css"),
        ]:
            response = client.get("/assets/" + filename)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(content_type)
            assert response.headers["x-content-type-options"] == "nosniff"
        assert client.get("/assets/config.py").status_code == 404
        assert client.get("/workspace", headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.get("/workspace", headers={"Host": "evil.test"}).status_code == 400
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("192.0.2.3", 12345),
    ) as client:
        assert client.get("/workspace").status_code == 403
        assert client.get("/assets/workspace.js").status_code == 403
