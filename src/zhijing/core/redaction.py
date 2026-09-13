"""Redact known credentials without relying on a particular provider key prefix."""

import html
import json
import re
from array import array
from urllib.parse import quote, quote_plus

# Each pass only contracts recognized escapes. Four passes cover mixed/nested
# representations without parsing recursive JSON or expanding arbitrary input.
_MAX_DECODE_PASSES = 4
_ESCAPE = re.compile(
    r"%[0-9a-fA-F]{2}|&(?:\#[xX][0-9a-fA-F]{1,8}(?![0-9a-fA-F]);?"
    r"|\#[0-9]{1,10}(?![0-9]);?|[A-Za-z][A-Za-z0-9]{1,31};?)"
    r'|\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])'
)


def _decode_escape(match):
    token = match.group()
    if token.startswith("%"):
        # Provider credentials are printable ASCII; decode bytes independently
        # so malformed UTF-8 cannot hide an otherwise valid credential.
        return chr(int(token[1:], 16))
    if token.startswith("&"):
        return html.unescape(token)
    return json.loads('"' + token + '"')


def _decoded_views(value):
    for _ in range(_MAX_DECODE_PASSES):
        decoded = _ESCAPE.sub(_decode_escape, value)
        if decoded == value:
            break
        yield decoded
        value = decoded


def _encoded_secret_spans(value, secrets):
    """Map decoded matches back to exact original spans, preserving other text."""
    # Compact integer arrays bound mapping memory to eight bytes per input
    # character, instead of allocating a tuple/object for every character.
    starts = array("I", range(len(value)))
    ends = array("I", range(1, len(value) + 1))
    for _ in range(_MAX_DECODE_PASSES):
        parts, next_starts, next_ends = [], array("I"), array("I")
        cursor = 0
        for match in _ESCAPE.finditer(value):
            first, last = match.span()
            parts.append(value[cursor:first])
            next_starts.extend(starts[cursor:first])
            next_ends.extend(ends[cursor:first])
            decoded = _decode_escape(match)
            parts.append(decoded)
            if decoded == match.group():
                next_starts.extend(starts[first:last])
                next_ends.extend(ends[first:last])
            else:
                next_starts.extend([starts[first]] * len(decoded))
                next_ends.extend([ends[last - 1]] * len(decoded))
            cursor = last
        parts.append(value[cursor:])
        next_starts.extend(starts[cursor:])
        next_ends.extend(ends[cursor:])
        decoded = "".join(parts)
        if decoded == value:
            break
        value, starts, ends = decoded, next_starts, next_ends
        for secret in secrets:
            position = value.find(secret)
            while position >= 0:
                yield starts[position], ends[position + len(secret) - 1]
                position = value.find(secret, position + 1)


class SecretRedactor:
    def __init__(self, values=()):
        variants = set()
        for value in values:
            if value:
                variants.update(
                    (value, quote(value, safe=""), quote_plus(value), json.dumps(value)[1:-1])
                )
        self._values = sorted(variants, key=len, reverse=True)

    def text(self, value: str) -> str:
        for secret in self._values:
            value = value.replace(secret, "[redacted]")
        # The fast path neither decodes nor rewrites ordinary user text. Only
        # allocate source mappings when a decoded view actually contains a key.
        if not self._values or not any(
            secret in decoded for decoded in _decoded_views(value) for secret in self._values
        ):
            return value
        spans = sorted(_encoded_secret_spans(value, self._values))
        merged = []
        for first, last in spans:
            if merged and first <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
            else:
                merged.append((first, last))
        parts, cursor = [], 0
        for first, last in merged:
            parts.extend((value[cursor:first], "[redacted]"))
            cursor = last
        parts.append(value[cursor:])
        return "".join(parts)

    def contains(self, value: str) -> bool:
        if any(secret in value for secret in self._values):
            return True
        return bool(self._values) and any(
            secret in decoded for decoded in _decoded_views(value) for secret in self._values
        )

    def value(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(key)): self.value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        return value


def client_redactor(client, extra=()) -> SecretRedactor:
    authorization = client.headers.get("authorization", "")
    bearer = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    return SecretRedactor((*extra, bearer))
