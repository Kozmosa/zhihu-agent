import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from zhijing.desktop_service import DesktopService, DesktopServiceError


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_owned_service_roundtrip_reuse_shutdown_and_durable_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHIJING_MODEL_PROVIDER", "extractive")
    ignored_data = tmp_path / "environment-must-not-override-explicit-data"
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(ignored_data))
    project = Path(__file__).resolve().parents[1]
    data = tmp_path / "isolated-data"
    port = free_port()
    owner = DesktopService(project, port=port, data_dir=data)
    reused = DesktopService(project, port=port, data_dir=data)
    try:
        assert owner.ensure_running()["model_provider"] == "extractive"
        assert owner.get_health()["status"] == "ok"
        items = [
            {
                "title": f"Desktop fixture {index}",
                "author_id": "desktop-fixture-author",
                "author_name": "Desktop fixture author",
                "text": "Active recall improves learning by retrieving knowledge without looking at notes.",
            }
            for index in (1, 2)
        ]
        with httpx.Client(base_url=owner.base_url, trust_env=False) as client:
            response = client.post("/api/v1/sources/import", json={"items": items})
            assert response.status_code == 200
        sources = owner.list_sources()
        assert len(sources) == 2
        assert owner.list_sources(offset=1, limit=1) == sources[1:2]
        answer = owner.ask(sources[0], "How does active recall improve learning?")
        assert answer["mode"] == "extractive"
        assert "recall" in answer["answer"].lower()
        assert answer["citations"]
        assert answer["citations"][0]["source_id"] == sources[0]["id"]

        assert reused.ensure_running()["status"] == "ok"
        reused.shutdown()
        assert owner.get_health()["status"] == "ok", "A reused server belongs to its starter"
        assert owner.ensure_running()["status"] == "ok"
        assert len(owner.list_sources()) == 2
        owner.shutdown()
        with socket.socket() as probe:
            probe.settimeout(0.5)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
        assert data.exists() and any(data.iterdir())
        assert not ignored_data.exists()
        assert owner.ensure_running()["status"] == "ok"
        assert {source["id"] for source in owner.list_sources()} == {
            source["id"] for source in sources
        }
    finally:
        reused.shutdown()
        owner.shutdown()


@contextmanager
def fixture_server(*, title="知境 ZhiJing Agent", post_status=200, post_body=None, redirect=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body):
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path == "/health":
                self.respond(
                    200, {"status": "ok", "version": "0.2.0", "model_provider": "extractive"}
                )
            elif self.path == "/openapi.json":
                self.respond(200, {"info": {"title": title}})
            elif self.path == "/workspace":
                if redirect:
                    self.send_response(302)
                    self.send_header("Location", "/redirect-target")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                content = b'<script nonce="fixture-session-token-123456789"></script>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            else:
                if self.path == "/redirect-target":
                    requests.append({"unexpected_redirect": self.path})
                self.respond(404, {"error": {"message": "Missing fixture endpoint"}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "token": self.headers.get("X-Zhijing-Token"),
                    "origin": self.headers.get("Origin"),
                }
            )
            self.respond(post_status, post_body or {})

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_refuses_occupied_port_with_another_application(tmp_path):
    with fixture_server(title="Different local application") as (port, _):
        service = DesktopService(tmp_path, port=port, data_dir=tmp_path / "data")
        try:
            with pytest.raises(DesktopServiceError):
                service.ensure_running()
            assert not (tmp_path / "data").exists()
            with httpx.Client(trust_env=False) as client:
                assert client.get(service.base_url + "/health").status_code == 200
        finally:
            service.shutdown()


def test_data_directory_priority_remains_explicit_then_environment_then_project(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ZHIJING_DATA_DIR", raising=False)
    project = tmp_path / "project"
    assert DesktopService(project).data_dir == project / "data"
    environment = tmp_path / "environment"
    monkeypatch.setenv("ZHIJING_DATA_DIR", str(environment))
    assert DesktopService(project).data_dir == environment
    explicit = tmp_path / "explicit"
    assert DesktopService(project, data_dir=explicit).data_dir == explicit
    assert not any(tmp_path.iterdir()), "Constructing a client must not create a data directory"


def test_session_page_redirect_is_not_followed_and_question_is_not_sent(tmp_path):
    with fixture_server(redirect=True) as (port, requests):
        service = DesktopService(tmp_path, port=port, data_dir=tmp_path / "data")
        try:
            service.ensure_running()
            with pytest.raises(DesktopServiceError, match="重定向"):
                service.ask({"id": "fixture-source", "author_id": "fixture-author"}, "Question")
            assert not requests
        finally:
            service.shutdown()


def test_ask_keeps_source_contract_redacts_server_errors_and_never_retries(tmp_path):
    canary = "fake-secret-that-must-never-appear-in-the-ui"
    with fixture_server(post_status=500, post_body={"error": {"message": canary}}) as (
        port,
        requests,
    ):
        service = DesktopService(tmp_path, port=port, data_dir=tmp_path / "data")
        try:
            service.ensure_running()
            source = {"id": "fixture-source", "author_id": "fixture-author"}
            with pytest.raises(DesktopServiceError) as captured:
                service.ask(source, "A synthetic question")
            assert canary not in str(captured.value)
            assert len(requests) == 1
            assert requests[0] == {
                "path": "/api/v1/author/ask",
                "token": "fixture-session-token-123456789",
                "origin": service.base_url,
                "body": {
                    "primary_source_id": "fixture-source",
                    "author_id": "fixture-author",
                    "question": "A synthetic question",
                },
            }
        finally:
            service.shutdown()
