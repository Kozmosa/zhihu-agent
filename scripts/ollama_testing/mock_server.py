"""A local Ollama-compatible fixture server; it does not run a language model."""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from .fixtures import model_response


@contextmanager
def mock_ollama():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/generate":
                self.send_error(404)
                return
            try:
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                prompt = json.loads(request["prompt"])
                calls.append(prompt)
                result = model_response(prompt)
                body = json.dumps({"response": json.dumps(result), "done": True}).encode()
            except (KeyError, ValueError, TypeError) as error:
                self.send_error(400, type(error).__name__)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
