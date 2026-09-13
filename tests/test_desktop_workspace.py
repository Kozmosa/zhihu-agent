"""The compact companion has its own page while the full workspace stays available."""

import re
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
        assert len(ids) == len(set(ids)), "Duplicate IDs break companion controls"
        assert any(
            tag == "body"
            and attributes.get("data-desktop") == "true"
            and attributes.get("data-surface") == "companion"
            for tag, attributes in page.elements
        )
        for capability in ("reading", "author", "cards", "facts", "knowledge"):
            assert {
                f"tool-tab-{capability}",
                f"tool-pane-{capability}",
                f"tool-form-{capability}",
                f"tool-run-{capability}",
                f"tool-result-{capability}",
            } <= set(ids)
        assert {"companion-root", "companion-source", "companion-import-form"} <= set(ids)
        assert not {"source-list", "import-form", "chat-root"} & set(ids)
        assert not {"zhihu-secret", "zhihu-config-form", "clear-zhihu-secret"} & set(ids)
        assert not any(
            tag == "input" and attributes.get("type") == "password"
            for tag, attributes in page.elements
        )
        assert "__CONFIG_TOKEN__" not in response.text
        assert "__CHAT_WIDGET__" not in response.text
        token = client.app.state.config_token
        nonce = re.search(r"nonce-([^']+)", response.headers["content-security-policy"])[1]
        assert nonce != token
        assets = []
        for tag, attributes in page.elements:
            if tag == "script" and "src" in attributes:
                assert attributes.get("nonce") == nonce
                assets.append(attributes["src"])
            if tag == "link" and attributes.get("rel") == "stylesheet":
                assets.append(attributes["href"])
        assert {"/assets/companion.js", "/assets/companion.css"} <= set(assets)
        assert not {
            "/assets/workspace.js",
            "/assets/workspace.css",
            "/assets/workspace-shell.js",
        } & set(assets)
        for asset in assets:
            assert asset.startswith("/assets/"), "Desktop resources must be self-contained"
            resource = client.get(asset)
            assert resource.status_code == 200, asset
            assert resource.headers["x-content-type-options"] == "nosniff"


def test_full_workspace_keeps_its_own_surface_and_assets(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        response = client.get("/workspace")
        assert response.status_code == 200
        page = PageElements(response.text)
        ids = {attributes["id"] for _, attributes in page.elements if "id" in attributes}
        assert {"source-list", "import-form", "chat-root"} <= ids
        assert "companion-root" not in ids
        assert "/assets/workspace.js" in response.text
        assert "/assets/workspace.css" in response.text
        assert "/assets/companion.js" not in response.text
        assert "/assets/companion.css" not in response.text


def test_desktop_page_keeps_local_origin_and_host_boundary(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12345),
    ) as client:
        for path in ("/desktop", "/assets/companion.js", "/assets/companion.css"):
            assert client.get(path, headers={"Origin": "https://outside.test"}).status_code == 403
            assert client.get(path, headers={"Host": "outside.test"}).status_code == 400
    with TestClient(
        create_app(Settings(data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("192.0.2.20", 12345),
    ) as client:
        for path in ("/desktop", "/assets/companion.js", "/assets/companion.css"):
            assert client.get(path).status_code == 403
