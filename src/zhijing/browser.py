"""Open model settings only after this server has become healthy."""

import json
import webbrowser
from threading import Event, Thread
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def open_docs_when_ready(server, base_url: str, stop: Event) -> Thread:
    def wait_until_ready():
        opener = build_opener(ProxyHandler({}))
        for _ in range(120):
            if stop.wait(0.25):
                return
            if not server.started:
                continue
            try:
                with opener.open(f"{base_url}/health", timeout=1) as response:
                    if json.load(response).get("status") == "ok":
                        webbrowser.open(f"{base_url}/")
                        return
            except (URLError, OSError, ValueError):
                continue

    thread = Thread(target=wait_until_ready, name="zhijing-open-docs", daemon=True)
    thread.start()
    return thread
