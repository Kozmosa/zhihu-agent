"""Real localhost HTTP mocks for both supported model protocols; no real inference."""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from .fixtures import model_response


@contextmanager
def mock_model(provider, responder=model_response):
    """Record task names only, never headers, prompts, credentials, or response text."""
    if provider not in {"ollama", "openai"}:
        raise ValueError("unsupported_mock_provider")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            expected = "/api/generate" if provider == "ollama" else "/v1/chat/completions"
            if self.path != expected:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2_000_000:
                    self.send_error(413)
                    return
                body = json.loads(self.rfile.read(size))
                if provider == "ollama":
                    prompt = json.loads(body["prompt"])
                else:
                    prompt = json.loads(body["messages"][-1]["content"])
                calls.append(prompt["task"])
                result = responder(prompt)
                if provider == "ollama":
                    payload = {"response": json.dumps(result), "done": True}
                else:
                    payload = {
                        "choices": [
                            {"message": {"content": json.dumps(result)}, "finish_reason": "stop"}
                        ]
                    }
                encoded = json.dumps(payload).encode("utf-8")
            except Exception:
                self.send_error(400, "Synthetic fixture failure")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    if provider == "openai":
        base_url += "/v1"
    try:
        yield base_url, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
