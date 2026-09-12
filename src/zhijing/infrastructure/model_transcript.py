"""Keep model diagnostics without persisting the active provider credential."""

import json

import httpx

from zhijing.infrastructure.transcript_context import get_context


def record_exchange(
    client: httpx.Client, *, provider: str, model: str, event: str, payload: dict
) -> None:
    context = get_context()
    if context is None:
        return
    authorization = client.headers.get("Authorization", "")
    credential = authorization.partition(" ")[2].strip()
    secrets = {value for value in (authorization, credential) if value}
    # The transcript includes serialized JSON envelopes and JSON nested inside model text.
    for _ in range(3):
        secrets.update(json.dumps(value, ensure_ascii=True)[1:-1] for value in tuple(secrets))
    variants = sorted(secrets, key=len, reverse=True)

    def redact(value):
        if isinstance(value, str):
            for secret in variants:
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, dict):
            return {redact(key): redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    context.transcript.append(
        session_id=context.session_id,
        run_id=context.run_id,
        step_id=context.step_id,
        attempt=context.attempt,
        event=event,
        provider=provider,
        model=redact(model),
        payload=redact(payload),
    )
