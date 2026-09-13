from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class TranscriptContext:
    transcript: object
    session_id: str
    run_id: str
    step_id: str
    attempt: int = 0

_current: ContextVar[TranscriptContext|None] = ContextVar('transcript_context', default=None)
def set_context(ctx): return _current.set(ctx)
def reset_context(token): _current.reset(token)
def get_context(): return _current.get()
