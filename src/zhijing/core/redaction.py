"""Redact known credentials without relying on a particular provider key prefix."""

import json
from urllib.parse import quote, quote_plus


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
        return value

    def contains(self, value: str) -> bool:
        if any(secret in value for secret in self._values):
            return True
        # The model returns JSON inside a JSON string; decode escaped codepoints
        # before allowing that content to be returned or recorded.
        try:
            decoded = json.dumps(json.loads(value), ensure_ascii=False)
        except (ValueError, TypeError):
            return False
        return any(secret in decoded for secret in self._values)

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
