"""Convert official search summaries into explicit, traceable excerpt drafts."""

import hashlib
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from pydantic import ValidationError

from zhijing.domain.models import SourceDraft, SourceProvenance
from zhijing.features.zhihu.schemas import ZhihuSearchResult
from zhijing.infrastructure.zhihu_search import ZhihuSearchClient

OFFICIAL_CONTENT_HOSTS = {"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}
HTML_TAGS = {
    "a",
    "abbr",
    "article",
    "b",
    "blockquote",
    "br",
    "code",
    "dd",
    "del",
    "div",
    "dl",
    "dt",
    "em",
    "figure",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "section",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "wbr",
}
BLOCK_TAGS = {"article", "blockquote", "br", "div", "hr", "li", "p", "section", "tr"}


class SummaryText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden.append(tag)
        elif not self.hidden:
            # HTMLParser also recognizes comparisons such as a<b and c>d as a
            # start tag with bare attributes. Keep that literal mathematical text.
            if attrs and any(value is None for _, value in attrs):
                self.parts.append(self.get_starttag_text())
            elif tag in BLOCK_TAGS:
                self.parts.append("\n")
            elif tag not in HTML_TAGS:
                self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag not in HTML_TAGS and tag not in {"script", "style"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = SummaryText()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def official_url(value) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(character.isspace() for character in value)
    ):
        raise ValueError("Invalid content URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in OFFICIAL_CONTENT_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not parsed.path.strip("/")
    ):
        raise ValueError("Invalid content URL")
    return value


def to_draft(item: dict, fetched_at: datetime) -> SourceDraft:
    raw_text = item.get("ContentText")
    title = item.get("Title")
    external_id = item.get("ContentID")
    content_type = item.get("ContentType")
    if (
        not isinstance(raw_text, str)
        or len(raw_text) > 200_000
        or not isinstance(title, str)
        or len(title) > 2000
        or not isinstance(external_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", external_id)
        or not isinstance(content_type, str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", content_type)
    ):
        raise ValueError("Incomplete or oversized search item")
    text = plain_text(raw_text)
    content_type = content_type.lower()
    url = official_url(item.get("Url"))
    canonical_url = urlsplit(url)._replace(query="", fragment="").geturl()
    author = item.get("AuthorName")
    if author is None or author == "":
        author = "未知作者"
    if not isinstance(author, str) or len(author) > 2000:
        raise ValueError("Invalid author name")
    return SourceDraft(
        title=plain_text(title),
        author_id=f"zhihu-content:{content_type}:{external_id}",
        author_name=plain_text(author) or "未知作者",
        text=text,
        url=url,
        origin="zhihu",
        content_extent="excerpt",
        provenance=SourceProvenance(
            external_id=external_id,
            content_type=content_type,
            canonical_url=canonical_url,
            fetched_at=fetched_at,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ),
    )


class ZhihuSearchService:
    def __init__(self, transport: ZhihuSearchClient):
        self.transport = transport

    def search(self, query: str, count: int) -> ZhihuSearchResult:
        data = self.transport.search(query, count)
        items, skipped = [], 0
        fetched_at = datetime.now(UTC)
        for item in data["Items"]:
            if not isinstance(item, dict) or self.transport.contains_secret(item):
                skipped += 1
                continue
            try:
                draft = to_draft(item, fetched_at)
            except (ValidationError, ValueError):
                skipped += 1
                continue
            if len(items) >= count:
                skipped += 1
            else:
                items.append(draft)
        reason = ""
        if not items:
            reason = (
                "返回结果缺少可导入摘要或来源信息，请修改关键词后重试。"
                if skipped
                else "知乎未返回搜索结果，请修改关键词后重试。"
            )
        return ZhihuSearchResult(items=items, skipped_count=skipped, empty_reason=reason)
