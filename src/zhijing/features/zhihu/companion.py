"""Receive user-selected browser text without receiving website login credentials."""

import hashlib
import json
import re
import secrets
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import Field, ValidationError

from zhijing.core.errors import DomainError
from zhijing.domain.models import Schema, SourceDraft, SourceProvenance
from zhijing.features.zhihu.web_schemas import ZhihuWebItem, ZhihuWebPreviewResult

MAX_CAPTURE_CHARS = 2_000_000
MAX_INBOX_CHARS = 8_000_000
MAX_INBOX_BATCHES = 20


class BrowserRecord(Schema):
    content_type: Literal["answer", "article"]
    external_id: str = Field(pattern=r"^[0-9]{1,30}$")
    question_id: str | None = Field(default=None, pattern=r"^[0-9]{1,30}$")
    title: str = Field(min_length=1, max_length=200)
    author_name: str = Field(default="知乎用户", min_length=1, max_length=200)
    author_url: str | None = Field(default=None, max_length=2048)
    text: str = Field(min_length=1, max_length=100_000)
    content_extent: Literal["fulltext", "excerpt", "unknown"] = "unknown"
    voteup_count: int | None = Field(default=None, strict=True, ge=0, le=10**12)
    voteup_is_approximate: bool = False
    url: str = Field(max_length=2048)
    captured_at: datetime


class BrowserCapture(Schema):
    request_id: UUID
    page_url: str = Field(min_length=1, max_length=2048)
    scope: Literal["page", "question", "author"] = "page"
    scope_id: str | None = Field(default=None, max_length=200)
    items: list[BrowserRecord] = Field(min_length=1, max_length=100)


def zhihu_url(value: str):
    try:
        parts = urlsplit(value)
        if (
            parts.scheme != "https"
            or parts.hostname not in {"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}
            or parts.username is not None
            or parts.password is not None
            or parts.port is not None
            or "\\" in value
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            raise ValueError
    except ValueError:
        raise DomainError("invalid_browser_capture", "浏览器采集的来源链接无效。", 422) from None
    return parts


def author_slug(value: str | None) -> str | None:
    if not value:
        return None
    parsed = zhihu_url(value)
    match = re.fullmatch(r"/(?:people|org)/([A-Za-z0-9][A-Za-z0-9_-]{0,99})/?", parsed.path)
    if parsed.hostname == "zhuanlan.zhihu.com" or not match:
        raise DomainError("invalid_browser_capture", "作者主页链接无效。", 422)
    return match[1]


def to_preview(capture: BrowserCapture) -> ZhihuWebPreviewResult:
    page = zhihu_url(capture.page_url)
    question = re.fullmatch(r"/question/([0-9]{1,30})(?:/answer/([0-9]{1,30}))?/?", page.path)
    profile = re.fullmatch(
        r"/(?:people|org)/([A-Za-z0-9][A-Za-z0-9_-]{0,99})(?:/answers)?/?", page.path
    )
    article = re.fullmatch(r"/p/([0-9]{1,30})/?", page.path)
    if (
        capture.scope == "question"
        and (
            not question or page.hostname == "zhuanlan.zhihu.com" or capture.scope_id != question[1]
        )
    ) or (
        capture.scope == "author"
        and (not profile or page.hostname == "zhuanlan.zhihu.com" or capture.scope_id != profile[1])
    ):
        raise DomainError("browser_scope_mismatch", "采集范围与来源页面不一致。", 422)
    total = sum(len(record.text) for record in capture.items)
    if total > MAX_CAPTURE_CHARS:
        raise DomainError("browser_capture_too_large", "本批内容过多，请分批发送。", 413)
    items, identities, hashes = [], set(), set()
    approximate = False
    for record in capture.items:
        parsed = zhihu_url(record.url)
        if record.content_type == "answer":
            expected = f"/question/{record.question_id}/answer/{record.external_id}"
            if (
                not record.question_id
                or parsed.hostname == "zhuanlan.zhihu.com"
                or parsed.path.rstrip("/") != expected
            ):
                raise DomainError("browser_scope_mismatch", "回答身份与原文链接不一致。", 422)
            canonical = (
                f"https://www.zhihu.com/question/{record.question_id}/answer/{record.external_id}"
            )
        else:
            if (
                parsed.hostname != "zhuanlan.zhihu.com"
                or parsed.path.rstrip("/") != f"/p/{record.external_id}"
                or record.question_id
            ):
                raise DomainError("browser_scope_mismatch", "文章身份与原文链接不一致。", 422)
            canonical = f"https://zhuanlan.zhihu.com/p/{record.external_id}"
        slug = author_slug(record.author_url)
        if capture.scope == "question" and (
            record.content_type != "answer" or record.question_id != capture.scope_id
        ):
            raise DomainError("browser_scope_mismatch", "回答不属于本次问题。", 422)
        if capture.scope == "author" and (
            record.content_type != "answer" or slug != capture.scope_id
        ):
            raise DomainError("browser_scope_mismatch", "回答不属于本次作者。", 422)
        if capture.scope == "page":
            # A single answer/article capture needs a verifiable relationship to its page.
            same_question = (
                question
                and record.content_type == "answer"
                and record.question_id == question[1]
                and (not question[2] or record.external_id == question[2])
                and page.hostname != "zhuanlan.zhihu.com"
            )
            same_article = (
                article
                and record.content_type == "article"
                and record.external_id == article[1]
                and page.hostname == "zhuanlan.zhihu.com"
            )
            same_author = (
                profile
                and record.content_type == "answer"
                and slug == profile[1]
                and page.hostname != "zhuanlan.zhihu.com"
            )
            if not (same_question or same_article or same_author):
                raise DomainError("browser_scope_mismatch", "内容与当前采集页面不一致。", 422)
        if record.content_extent == "excerpt" or not record.text.strip():
            continue
        digest = hashlib.sha256(record.text.encode("utf-8")).hexdigest()
        identity = (record.content_type, record.external_id)
        if identity in identities or digest in hashes:
            continue
        identities.add(identity)
        hashes.add(digest)
        # DOM availability does not independently establish the website's full-text status.
        try:
            draft = SourceDraft(
                title=record.title,
                author_name=record.author_name,
                author_id=f"zhihu-profile:{slug}"
                if slug
                else f"zhihu-browser:{record.content_type}:{record.external_id}",
                text=record.text,
                url=canonical,
                topics=[f"知乎问题:{record.question_id}"] if record.question_id else [],
                origin="zhihu",
                content_extent="unknown",
                provenance=SourceProvenance(
                    external_id=record.external_id,
                    content_type=record.content_type,
                    canonical_url=canonical,
                    fetched_at=record.captured_at,
                    content_hash=digest,
                    external_author_id=f"profile:{slug}" if slug else None,
                ),
            )
        except ValidationError:
            raise DomainError(
                "invalid_browser_capture", "采集内容缺少有效标题或正文。", 422
            ) from None
        approximate = approximate or record.voteup_is_approximate
        items.append(
            ZhihuWebItem(
                draft=draft,
                answer_id=record.external_id,
                question_id=record.question_id or "",
                voteup_count=record.voteup_count,
            )
        )
    if not items:
        raise DomainError("browser_capture_empty", "没有可接收的正文；请先展开回答再采集。", 422)
    items.sort(
        key=lambda item: item.voteup_count if item.voteup_count is not None else -1, reverse=True
    )
    return ZhihuWebPreviewResult(
        items=items,
        scanned_count=len(capture.items),
        skipped_count=len(capture.items) - len(items),
        pages_fetched=1,
        has_more=False,
        stop_reason="browser_capture",
        warning="来自浏览器已加载的页面文字，正文完整性未独立核验；仅按本次采集结果排序。"
        + (" 部分赞同数为页面缩写的近似值。" if approximate else ""),
        target_label=items[0].draft.title
        if capture.scope != "author"
        else items[0].draft.author_name,
    )


class CompanionInbox:
    """Pairing hash persists; bounded pending captures remain in this app session."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "browser-companion-pairing.json"
        self.lock = RLock()
        self.batches: OrderedDict[str, dict] = OrderedDict()
        self.token_hash = ""
        if self.path.is_file():
            try:
                value = json.loads(self.path.read_text("utf-8"))
                candidate = value.get("token_sha256", "")
                if isinstance(candidate, str) and re.fullmatch(r"[a-f0-9]{64}", candidate):
                    self.token_hash = candidate
            except (OSError, ValueError, AttributeError):
                pass

    def pair(self) -> str:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"token_sha256": digest, "paired_at": datetime.now(UTC).isoformat()}),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self.token_hash = digest
        return token

    def authenticate(self, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
            raise DomainError("companion_not_paired", "请在知境工作台连接采集脚本。", 403)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            if not self.token_hash or not secrets.compare_digest(self.token_hash, digest):
                raise DomainError(
                    "companion_not_paired", "采集连接已失效，请回到知境重新连接。", 403
                )

    def receive(self, capture: BrowserCapture) -> dict:
        fingerprint = hashlib.sha256(capture.model_dump_json().encode()).hexdigest()
        request_id = str(capture.request_id)
        with self.lock:
            for batch in self.batches.values():
                if batch["request_id"] == request_id:
                    if batch["fingerprint"] != fingerprint:
                        raise DomainError(
                            "capture_id_conflict",
                            "本次发送标识与之前的内容不一致，请重新采集。",
                            409,
                        )
                    return {
                        "batch_id": batch["batch_id"],
                        "count": len(batch["result"].items),
                        "duplicate": True,
                    }
            result = to_preview(capture)
            size = sum(len(item.draft.text) for item in result.items)
            if (
                len(self.batches) >= MAX_INBOX_BATCHES
                or sum(batch["size"] for batch in self.batches.values()) + size > MAX_INBOX_CHARS
            ):
                raise DomainError(
                    "companion_inbox_full", "知境接收列表已满，请先导入并移除已处理批次。", 429
                )
            batch_id = uuid4().hex
            self.batches[batch_id] = {
                "batch_id": batch_id,
                "request_id": request_id,
                "fingerprint": fingerprint,
                "result": result,
                "size": size,
                "page_url": capture.page_url,
                "captured_at": datetime.now(UTC).isoformat(),
                "scope": capture.scope,
            }
            return {"batch_id": batch_id, "count": len(result.items), "duplicate": False}

    def summaries(self) -> list[dict]:
        with self.lock:
            return [
                {
                    "batch_id": batch["batch_id"],
                    "count": len(batch["result"].items),
                    "captured_at": batch["captured_at"],
                    "page_url": batch["page_url"],
                    "scope": batch["scope"],
                    "label": batch["result"].target_label,
                }
                for batch in reversed(self.batches.values())
            ]

    def get(self, batch_id: str) -> dict:
        with self.lock:
            batch = self.batches.get(batch_id)
            if batch is None:
                raise DomainError(
                    "capture_not_found", "该采集批次已移除或服务已重启，请重新发送。", 404
                )
            return {"batch_id": batch_id, **batch["result"].model_dump(mode="json")}

    def dismiss(self, batch_id: str) -> bool:
        with self.lock:
            return self.batches.pop(batch_id, None) is not None

    def close(self):
        with self.lock:
            self.batches.clear()
