"""The desktop workspace exposes user capabilities without configuration controls."""

from html.parser import HTMLParser

from fastapi.testclient import TestClient

from zhijing.app import create_app
from zhijing.core.config import Settings


class PageElements(HTMLParser):
    def __init__(self, document):
        super().__init__()
        self.elements = []
        self.feed(document)

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


def test_desktop_page_exposes_five_capabilities_without_admin_credentials(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        response = client.get("/desktop")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        page = PageElements(response.text)
        ids = [attributes["id"] for _, attributes in page.elements if "id" in attributes]
        assert len(ids) == len(set(ids)), "Duplicate IDs break shared workspace handlers"
        assert any("data-desktop" in attributes for _, attributes in page.elements)
        for capability in ("reading", "author", "cards", "facts", "knowledge"):
            assert {f"tab-{capability}", f"{capability}-form", f"{capability}-result"} <= set(ids)
        assert {"source-list", "import-form", "export-tsv", "export-apkg"} <= set(ids)
        assert not {"zhihu-secret", "zhihu-config-form", "clear-zhihu-secret"} & set(ids)
        assert not any(
            tag == "input" and attributes.get("type") == "password"
            for tag, attributes in page.elements
        )
        assert "__CONFIG_TOKEN__" not in response.text
        assert "__CHAT_WIDGET__" not in response.text
        token = client.app.state.config_token
        assert "nonce-" + token in response.headers["content-security-policy"]
        assets = []
        for tag, attributes in page.elements:
            if tag == "script" and "src" in attributes:
                assert attributes.get("nonce") == token
                assets.append(attributes["src"])
            if tag == "link" and attributes.get("rel") == "stylesheet":
                assets.append(attributes["href"])
        assert "/assets/workspace.js" in assets
        for asset in assets:
            assert asset.startswith("/assets/"), "Desktop resources must be self-contained"
            resource = client.get(asset)
            assert resource.status_code == 200, asset
            assert resource.headers["x-content-type-options"] == "nosniff"


def test_desktop_page_keeps_local_origin_and_host_boundary(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        assert client.get("/desktop", headers={"Origin": "https://outside.test"}).status_code == 403
        assert client.get("/desktop", headers={"Host": "outside.test"}).status_code == 400
    with TestClient(
        create_app(Settings(data_dir=tmp_path)), client=("192.0.2.20", 12345)
    ) as client:
        assert client.get("/desktop").status_code == 403
