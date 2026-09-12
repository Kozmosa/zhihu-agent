"""Check service-page compatibility without creating a Tk window or real server."""

import queue
from types import SimpleNamespace

import httpx
import pytest

from zhijing.desktop_ui import DesktopAssistant


@pytest.mark.parametrize(
    ("document", "status", "ready"),
    [
        ('<body data-desktop="true">Old full workspace</body>', 200, False),
        ('<body data-desktop="false" data-surface="companion"></body>', 200, False),
        ('<body data-desktop="true" data-surface="companion"></body>', 200, True),
        ('<body data-desktop="true" data-surface="companion"></body>', 503, False),
    ],
)
def test_startup_requires_current_companion_surface(monkeypatch, document, status, ready):
    def respond(request):
        assert str(request.url) == "http://127.0.0.1:12345/desktop"
        return httpx.Response(status, text=document)

    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    assistant = DesktopAssistant.__new__(DesktopAssistant)
    assistant.service = SimpleNamespace(
        base_url="http://127.0.0.1:12345", ensure_running=lambda: None
    )
    assistant._closed = False
    assistant._starting = False
    assistant._events = queue.Queue()
    assistant._start_service()
    actual_ready, message = assistant._events.get(timeout=2)
    assert actual_ready is ready
    assert message == "" if ready else "退出旧版" in message
