"""Read bounded same-site web feeds without storing browser credentials."""

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qs, urlsplit

import httpx
from pydantic import ValidationError

from zhijing.core.errors import DomainError
from zhijing.domain.models import SourceDraft, SourceProvenance
from zhijing.features.zhihu.service import plain_text
from zhijing.features.zhihu.web_schemas import (
    ZhihuWebItem,
    ZhihuWebPreviewRequest,
    ZhihuWebPreviewResult,
)

MAX_PAGES = 10
PAGE_SIZE = 20
MAX_SECONDS = 45.0
MAX_RESPONSE_BYTES = 8_000_000
DELAY_SECONDS = 1.0
_ID = re.compile(r"[0-9]{1,30}")
_AUTHOR_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SLUG = r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}"
_INCLUDE = (
    "data[*].content,excerpt,author,question,voteup_count,updated_time,"
    "is_normal,is_deleted,is_paid,paid_info,is_truncated,content_truncated"
)
_WARNINGS = {
    "exhausted": "已读完本次网页接口返回的回答。",
    "max_items": "已达到本次导入数量上限，可调整数量后重新预览。",
    "page_limit": "已达到本次最多 10 页、200 条回答的读取上限。",
    "deadline": "已达到本次约 45 秒的读取时限。",
    "login_required": "知乎要求登录；请在设置中提供本人登录状态后重试。",
    "access_denied": "知乎拒绝了本次网页读取；请在浏览器中检查登录或验证状态。",
    "rate_limited": "知乎限制了请求频率，本次读取已停止，请稍后重试。",
    "redirect_requires_browser": "知乎要求浏览器跳转或验证，本次读取已停止。",
    "browser_required": "知乎返回了登录或验证网页，本次读取已停止。",
    "web_network_error": "网页网络请求失败，本次读取已停止。",
    "web_http_error": "知乎暂时未提供可读取的网页数据。",
    "web_shape_changed": "网页数据格式与预期不符，本次读取已停止。",
    "unsafe_pagination": "网页分页信息与当前目标不一致，本次读取已停止。",
    "pagination_stalled": "网页返回了重复回答页或无效分页，本次读取已停止。",
    "scope_mismatch": "网页返回的回答不属于所选问题或作者，本次读取已停止。",
    "response_too_large": "网页返回的数据过大，本次读取已停止。",
    "sensitive_response": "网页响应包含登录状态内容，本次读取已停止且未导入该页。",
}


class _WebStop(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _contains_sensitive(value, secrets: list[str]) -> bool:
    # Inspect decoded values, not JSON serialization: quotes and backslashes are
    # escaped by JSON and character references may be decoded into source text.
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            decoded = unescape(item)
            if any(secret in item or secret in decoded for secret in secrets):
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _target(body: ZhihuWebPreviewRequest) -> tuple[str, str]:
    value = body.url.strip()
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"www.zhihu.com", "zhihu.com"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and not any(c.isspace() or ord(c) < 32 for c in value)
            and "\\" not in value
        )
        pattern = (
            r"/question/([0-9]{1,30})(?:/answer/[0-9]{1,30})?/?"
            if body.mode == "question"
            else rf"/(?:people|org)/({_SLUG})(?:/answers)?/?"
        )
        match = re.fullmatch(pattern, parsed.path) if valid else None
    except ValueError:
        match = None
    if not match:
        raise DomainError(
            "zhihu_web_invalid_url",
            "请输入与所选模式对应的知乎 HTTPS 问题链接或作者主页链接。",
            422,
        )
    return match[1], value


def _identifier(value, *, author=False) -> str:
    # bool is an int in Python, but it is never a platform identifier.
    if type(value) not in {str, int}:
        raise ValueError("invalid_identifier")
    value = str(value)
    if not (_AUTHOR_ID if author else _ID).fullmatch(value):
        raise ValueError("invalid_identifier")
    return value


def _author_id(author: dict, raw: dict) -> str | None:
    value = author.get("id")
    if raw.get("is_anonymous") or value in {None, "", "0", 0}:
        return None
    return _identifier(value, author=True)


def _cursor(paging, path: str, offset: int, count: int) -> int | None:
    if not isinstance(paging, dict) or type(paging.get("is_end")) is not bool:
        raise _WebStop("web_shape_changed")
    if paging["is_end"]:
        return None
    value = paging.get("next")
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.zhihu.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.path != path
            or parsed.fragment
            or any(c.isspace() or ord(c) < 32 for c in value)
            or "\\" in value
        ):
            raise ValueError
        offsets = parse_qs(parsed.query, keep_blank_values=True).get("offset", [])
        if len(offsets) != 1 or not re.fullmatch(r"[0-9]{1,7}", offsets[0]):
            raise ValueError
    except ValueError as exc:
        raise _WebStop("unsafe_pagination") from exc
    next_offset = int(offsets[0])
    if count == 0 or not offset < next_offset <= 1_000_000:
        raise _WebStop("pagination_stalled")
    return next_offset


def _item(raw: dict, target_id: str, title: str, member_id: str | None) -> ZhihuWebItem:
    if not isinstance(raw, dict) or raw.get("type") != "answer":
        raise ValueError("not_answer")
    question, author = raw.get("question"), raw.get("author")
    if not isinstance(question, dict) or not isinstance(author, dict):
        raise ValueError("missing_identity")
    answer_id = _identifier(raw.get("id"))
    question_id = _identifier(question.get("id"))
    author_id = _author_id(author, raw)
    if (member_id is None and question_id != target_id) or (
        member_id is not None and author_id != member_id
    ):
        raise _WebStop("scope_mismatch")
    content = raw.get("content")
    if (
        raw.get("is_normal") is not True
        or raw.get("is_deleted")
        or raw.get("paid_info")
        or raw.get("paidInfo")
        or raw.get("is_paid")
        or raw.get("is_truncated")
        or raw.get("content_truncated")
        or not isinstance(content, str)
        or not content.strip()
        or len(content) > 2_000_000
    ):
        raise ValueError("incomplete_answer")
    votes = raw.get("voteup_count")
    if votes is not None and (type(votes) is not int or votes < 0):
        raise ValueError("invalid_votes")
    text = plain_text(content)
    question_title = title if member_id is None else question.get("title")
    if not isinstance(question_title, str):
        raise ValueError("missing_question_title")
    url = f"https://www.zhihu.com/question/{question_id}/answer/{answer_id}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ZhihuWebItem(
        answer_id=answer_id,
        question_id=question_id,
        voteup_count=votes,
        draft=SourceDraft(
            title=plain_text(question_title),
            author_id=(f"zhihu-author:{author_id}" if author_id else f"zhihu-answer:{answer_id}"),
            author_name=author.get("name") or "知乎用户",
            text=text,
            url=url,
            topics=[f"知乎问题:{question_id}"],
            origin="zhihu",
            content_extent="fulltext",
            provenance=SourceProvenance(
                external_id=answer_id,
                content_type="answer",
                canonical_url=f"https://www.zhihu.com/answer/{answer_id}",
                fetched_at=datetime.now(UTC),
                content_hash=digest,
                external_author_id=author_id,
            ),
        ),
    )


class ZhihuWebService:
    def __init__(self, *, transport=None, sleep=time.sleep):
        self.transport = transport
        self.sleep = sleep

    def preview(self, body: ZhihuWebPreviewRequest, cookie: str = "") -> ZhihuWebPreviewResult:
        target_id, _ = _target(body)
        if (
            not isinstance(cookie, str)
            or len(cookie) > 16_384
            or not cookie.isascii()
            or any(ord(c) < 32 or ord(c) == 127 for c in cookie)
        ):
            raise DomainError("zhihu_web_invalid_cookie", "登录状态格式无效，请重新设置。", 422)
        # Retained only for this request; responses must never echo credentials into sources.
        sensitive = [cookie] if cookie else []
        sensitive += [
            part.partition("=")[2].strip()
            for part in cookie.split(";")
            if len(part.partition("=")[2].strip()) >= 8
        ]
        sensitive += [
            value[1:-1]
            for value in sensitive[1:]
            if value.startswith('"') and value.endswith('"') and len(value) >= 10
        ]
        deadline = time.monotonic() + MAX_SECONDS
        headers = {
            "User-Agent": "ZhiJing/0.2 (local user-requested import)",
            "Accept": "application/json",
        }
        if cookie:
            headers["Cookie"] = cookie
        request_count = 0

        def get_json(client, path, params=None):
            nonlocal request_count
            remaining = deadline - time.monotonic()
            if remaining <= (DELAY_SECONDS if request_count else 0):
                raise _WebStop("deadline")
            if request_count:
                self.sleep(DELAY_SECONDS)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _WebStop("deadline")
            request_count += 1
            try:
                with client.stream(
                    "GET", path, params=params, timeout=min(10.0, remaining)
                ) as response:
                    status = response.status_code
                    if status in {401, 403, 429}:
                        raise _WebStop(
                            {401: "login_required", 403: "access_denied", 429: "rate_limited"}[
                                status
                            ]
                        )
                    if 300 <= status < 400:
                        raise _WebStop("redirect_requires_browser")
                    if status != 200:
                        raise _WebStop("web_http_error")
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            raise _WebStop("deadline")
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise _WebStop("response_too_large")
                        chunks.append(chunk)
                    payload = json.loads(b"".join(chunks))
            except httpx.HTTPError as exc:
                raise _WebStop("web_network_error") from exc
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise _WebStop("browser_required") from exc
            if not isinstance(payload, dict):
                raise _WebStop("web_shape_changed")
            if sensitive and _contains_sensitive(payload, sensitive):
                raise _WebStop("sensitive_response")
            if payload.get("error"):
                raise _WebStop("browser_required")
            return payload

        items: list[ZhihuWebItem] = []
        scanned = skipped = pages = 0
        seen_ids, seen_hashes, seen_pages = set(), set(), set()
        label = f"知乎问题 {target_id}" if body.mode == "question" else f"知乎作者 {target_id}"
        stop, has_more = "page_limit", True
        try:
            with httpx.Client(
                base_url="https://www.zhihu.com",
                headers=headers,
                follow_redirects=False,
                transport=self.transport,
                trust_env=False,
            ) as client:
                member_id = None
                if body.mode == "question":
                    metadata = get_json(client, f"/api/v4/questions/{target_id}")
                    if _identifier(metadata.get("id")) != target_id:
                        raise _WebStop("scope_mismatch")
                    title = metadata.get("title")
                    if not isinstance(title, str) or not title.strip() or len(title) > 200:
                        raise _WebStop("web_shape_changed")
                    clean_title = plain_text(title)
                    if sensitive and _contains_sensitive(clean_title, sensitive):
                        raise _WebStop("sensitive_response")
                    label = clean_title
                    path = f"/api/v4/questions/{target_id}/answers"
                else:
                    metadata = get_json(client, f"/api/v4/members/{target_id}")
                    member_id = _identifier(metadata.get("id"), author=True)
                    if member_id == "0" or target_id not in {metadata.get("url_token"), member_id}:
                        raise _WebStop("scope_mismatch")
                    name = metadata.get("name")
                    if not isinstance(name, str) or not name.strip() or len(name) > 200:
                        raise _WebStop("web_shape_changed")
                    label, title = name, ""
                    path = f"/api/v4/members/{target_id}/answers"
                offset = 0
                for _ in range(MAX_PAGES):
                    payload = get_json(
                        client,
                        path,
                        {
                            "include": _INCLUDE,
                            "offset": offset,
                            "limit": PAGE_SIZE,
                            "sort_by": "default" if body.mode == "question" else "voteups",
                        },
                    )
                    pages += 1
                    rows = payload.get("data")
                    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                        raise _WebStop("web_shape_changed")
                    scanned += len(rows)
                    cursor = _cursor(payload.get("paging"), path, offset, len(rows))
                    fingerprint = hashlib.sha256(
                        json.dumps(rows, sort_keys=True).encode()
                    ).hexdigest()
                    if rows and fingerprint in seen_pages:
                        skipped += len(rows)
                        raise _WebStop("pagination_stalled")
                    # Validate a whole page before retaining it, so a mixed-author or
                    # wrong-question page cannot contribute an apparently valid subset.
                    page_items, page_skipped = [], 0
                    for raw in rows:
                        try:
                            candidate = _item(raw, target_id, title, member_id)
                        except (ValueError, TypeError, ValidationError):
                            page_skipped += 1
                            continue
                        if sensitive and _contains_sensitive(
                            candidate.model_dump(mode="json"), sensitive
                        ):
                            raise _WebStop("sensitive_response")
                        if (candidate.voteup_count or 0) < body.min_votes:
                            page_skipped += 1
                            continue
                        page_items.append(candidate)
                    seen_pages.add(fingerprint)
                    skipped += page_skipped
                    for candidate in page_items:
                        digest = candidate.draft.provenance.content_hash
                        if candidate.answer_id in seen_ids or digest in seen_hashes:
                            skipped += 1
                            continue
                        seen_ids.add(candidate.answer_id)
                        seen_hashes.add(digest)
                        items.append(candidate)
                    items.sort(
                        key=lambda item: item.voteup_count if item.voteup_count is not None else -1,
                        reverse=True,
                    )
                    if cursor is None:
                        stop, has_more = "exhausted", False
                        break
                    if len(items) >= body.max_items:
                        stop, has_more = "max_items", True
                        break
                    offset = cursor
        except _WebStop as exc:
            stop = exc.code
        except (ValueError, TypeError, ValidationError):
            stop = "web_shape_changed"
        if len(items) > body.max_items and stop == "exhausted":
            stop, has_more = "max_items", True
        items = items[: body.max_items]
        # Include pages rejected atomically and eligible answers outside the selected
        # count, so every scanned row is either returned or visibly skipped.
        skipped = scanned - len(items)
        warning = (
            _WARNINGS[stop] + " 本次仅按已读取回答的赞同数排序，不保证是全站或全部回答中的最高赞。"
            " 仅提取可用且未标记付费或截断的文字正文；赞同数不代表事实正确。"
        )
        if not items:
            warning += " 本次未找到符合条件的完整回答。"
        return ZhihuWebPreviewResult(
            items=items,
            scanned_count=scanned,
            skipped_count=skipped,
            pages_fetched=pages,
            has_more=has_more,
            stop_reason=stop,
            warning=warning,
            target_label=label,
        )
