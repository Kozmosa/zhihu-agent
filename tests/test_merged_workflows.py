"""Shared identities and visible entry points across the two merged branches."""

from html.parser import HTMLParser

import pytest

from zhijing.core.errors import DomainError
from zhijing.features.zhihu.companion import BrowserCapture, to_preview
from zhijing.features.zhihu.question_models import raw_answer_to_draft

TEXT = "主动回忆需要主动提取所学内容，间隔复习则安排多次回顾。"


def capture(author_kind="people", scope="question"):
    return BrowserCapture.model_validate(
        {
            "request_id": "dfeaf977-f956-4350-9161-9b649fcdeee4",
            "page_url": "https://www.zhihu.com/question/123"
            if scope == "question"
            else "https://www.zhihu.com/people/alice/answers",
            "scope": scope,
            "scope_id": "123" if scope == "question" else "alice",
            "items": [
                {
                    "content_type": "answer",
                    "external_id": "456",
                    "question_id": "123",
                    "title": "怎样安排学习？",
                    "author_name": "测试作者",
                    "author_url": f"https://www.zhihu.com/{author_kind}/alice",
                    "url": "https://www.zhihu.com/question/123/answer/456",
                    "text": TEXT,
                    "captured_at": "2026-09-13T00:00:00Z",
                }
            ],
        }
    )


def test_plugin_and_desktop_answers_share_library_author_and_question(client):
    plugin = to_preview(capture()).items[0].draft
    desktop = raw_answer_to_draft(
        {
            "question_id": "123",
            "answer_id": "457",
            "title": "怎样安排学习？",
            "author_name": "测试作者",
            "author_url": "https://www.zhihu.com/people/alice",
            "url": "https://www.zhihu.com/question/123/answer/457",
            "text": TEXT,
        },
        "https://www.zhihu.com/question/123",
    )
    assert plugin.author_id == desktop.author_id == "zhihu-author:people:alice"
    assert plugin.provenance.external_author_id == desktop.provenance.external_author_id
    saved = client.post(
        "/api/v1/sources/import",
        json={"items": [item.model_dump(mode="json") for item in (plugin, desktop)]},
    )
    assert saved.status_code == 200
    for by in ("author", "question"):
        groups = client.get("/api/v1/sources/groups", params={"by": by}).json()
        assert len(groups["items"]) == 1
        assert groups["items"][0]["count"] == 2
    ids = [item["id"] for item in saved.json()]
    deleted = client.post("/api/v1/sources/delete", json={"source_ids": ids})
    assert deleted.status_code == 200
    assert client.get("/api/v1/sources").json() == []
    assert client.get("/api/v1/sources/groups", params={"by": "author"}).json()["items"] == []


def test_people_and_org_with_same_slug_are_distinct_and_cannot_cross_author_scope():
    person = to_preview(capture()).items[0].draft
    organization = to_preview(capture("org")).items[0].draft
    assert person.author_id != organization.author_id
    with pytest.raises(DomainError, match="本次作者"):
        to_preview(capture("org", "author"))


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "a" and attributes.get("id"):
            self.links[attributes["id"]] = attributes.get("href")


def test_settings_and_capture_entry_points_are_reachable(client):
    for page, identifier in (
        ("/desktop", "companion-settings-link"),
        ("/workspace", "workspace-settings-link"),
    ):
        links = Links(client.get(page).text).links
        assert links[identifier] == "/admin"
        settings = client.get(links[identifier])
        assert settings.status_code == 200 and 'id="model"' in settings.text
    assert (
        Links(client.get("/desktop").text).links["companion-capture-link"] == "/workspace#companion"
    )
    assert client.get("/assets/zhihu-companion.user.js").status_code == 200
