"""Establish an in-memory session for trusted local CLI/test clients."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit


class PageTokens(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.tokens: set[str] = set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            token = dict(attrs).get("data-config-token", "")
            if re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
                self.tokens.add(token)


def connect_local_client(client) -> None:
    """Use the same local workspace handshake as the UI; never persist the token."""
    base = urlsplit(str(client.base_url))
    if (
        base.scheme not in {"http", "https"}
        or base.hostname not in {"127.0.0.1", "localhost", "::1"}
        or base.username is not None
        or base.password is not None
        or base.query
        or base.fragment
        or base.path not in {"", "/"}
    ):
        raise ValueError("API 会话仅支持本机知境服务地址。")
    response = client.get("/workspace", follow_redirects=False)
    response.raise_for_status()
    tokens = PageTokens(response.text).tokens
    if len(tokens) != 1:
        raise ValueError("无法读取知境 API 会话，请确认服务版本。")
    client.headers["X-Zhijing-Token"] = next(iter(tokens))
    client.headers["Origin"] = str(client.base_url).rstrip("/")
