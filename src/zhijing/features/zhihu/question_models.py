"""Validate browser-collected answers before exposing reviewable source drafts."""

import hashlib
import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import SplitResult, urlsplit

from pydantic import Field

from zhijing.domain.models import Schema, SourceDraft, SourceProvenance

OFFICIAL_HOSTS = {"zhihu.com", "www.zhihu.com", "m.zhihu.com"}
QUESTION_PATH = re.compile(r"/question/([0-9]{1,30})/?")
ANSWER_PATH = re.compile(r"/question/([0-9]{1,30})/answer/([0-9]{1,30})/?")
AUTHOR_PATH = re.compile(r"/(people|org)/([A-Za-z0-9][A-Za-z0-9_-]{0,127})/?")
JobStatus = Literal["running", "needs_login", "ready", "failed", "cancelled"]


def _official_parts(value: str) -> SplitResult:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("Invalid Zhihu URL")
    value = value.strip()
    if not value or any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("Invalid Zhihu URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in OFFICIAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443 if parsed.scheme == "https" else 80}
    ):
        raise ValueError("Invalid Zhihu URL")
    return parsed


def normalize_question_url(url: str) -> str:
    match = QUESTION_PATH.fullmatch(_official_parts(url).path)
    if match is None:
        raise ValueError("A Zhihu question URL is required")
    return "https://www.zhihu.com/question/" + match[1]


def question_id_from_url(url: str) -> str:
    return normalize_question_url(url).rsplit("/", 1)[1]


def _numeric_identifier(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,30}", value):
        raise ValueError("Invalid answer identifier")
    return value


def _text(value, maximum: int, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\r\n\t" for character in value)
    ):
        raise ValueError("Invalid answer text")
    value = value.strip()
    if required and not value:
        raise ValueError("Missing answer text")
    value.encode("utf-8")
    return value


def raw_answer_to_draft(raw: dict, question_url: str) -> SourceDraft:
    if not isinstance(raw, dict):
        raise ValueError("Invalid answer")
    question_id = question_id_from_url(question_url)
    answer_id = _numeric_identifier(raw.get("answer_id"))
    if _numeric_identifier(raw.get("question_id")) != question_id:
        raise ValueError("Answer belongs to another question")
    answer_path = ANSWER_PATH.fullmatch(_official_parts(raw.get("url")).path)
    if answer_path is None or answer_path.groups() != (question_id, answer_id):
        raise ValueError("Answer URL does not match its identifiers")
    canonical = f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
    title = _text(raw.get("title"), 2000)[:200]
    text = _text(raw.get("text"), 100_000)
    author_name = _text(raw.get("author_name"), 2000, required=False)[:200] or "未知作者"
    author_id = f"zhihu-content:answer:{answer_id}"
    external_author_id = None
    try:
        author_path = AUTHOR_PATH.fullmatch(_official_parts(raw.get("author_url")).path)
        if author_path:
            external_author_id = f"{author_path[1]}:{author_path[2]}"
            author_id = "zhihu-author:" + external_author_id
    except ValueError:
        pass
    return SourceDraft(
        title=title,
        author_id=author_id,
        author_name=author_name,
        text=text,
        url=canonical,
        origin="zhihu",
        content_extent="unknown",
        provenance=SourceProvenance(
            external_id=answer_id,
            content_type="answer",
            canonical_url=canonical,
            fetched_at=datetime.now(UTC),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            external_author_id=external_author_id,
        ),
    )


class QuestionStartRequest(Schema):
    url: str = Field(min_length=1, max_length=2048)
    count: int = Field(default=10, ge=1, le=20, strict=True)


class QuestionJobView(Schema):
    id: str
    status: JobStatus
    question_url: str
    requested_count: int
    collected_count: int
    message: str
    items: list[SourceDraft] = Field(max_length=20)
    terminal: bool
