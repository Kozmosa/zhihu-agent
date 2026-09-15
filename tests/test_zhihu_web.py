"""Synthetic website responses validate imports; they are not live access evidence."""

import hashlib
import json

import httpx
import pytest

from zhijing.core.errors import DomainError
from zhijing.features.zhihu import web_service
from zhijing.features.zhihu.web_schemas import ZhihuWebPreviewRequest
from zhijing.features.zhihu.web_service import ZhihuWebService

QUESTION_PATH = "/api/v4/questions/100/answers"
AUTHOR_PATH = "/api/v4/members/sample-author/answers"


def answer(aid="1000", qid="100", author_id="stable-author", **changes):
    return {
        "id": aid,
        "type": "answer",
        "question": {"id": qid, "title": f"问题 {qid}"},
        "author": {"id": author_id, "url_token": "sample-author", "name": "样例作者"},
        "is_normal": True,
        "voteup_count": 120,
        "content": f"<p>回答 {aid} 的完整第一段。</p><p>第二段保留来源与限制。</p>",
    } | changes


def page(rows, *, path=QUESTION_PATH, offset=None):
    paging = {"is_end": offset is None}
    if offset is not None:
        paging["next"] = f"https://www.zhihu.com{path}?offset={offset}&limit=20"
    return httpx.Response(200, json={"data": rows, "paging": paging})


def preview(handler, *, mode="question", cookie="", sleep=lambda _: None, **options):
    calls = []

    def site(request):
        calls.append(request)
        if request.url.path == "/api/v4/questions/100":
            return httpx.Response(200, json={"id": 100, "title": "共同问题"})
        if request.url.path == "/api/v4/members/sample-author":
            return httpx.Response(
                200,
                json={
                    "id": "stable-author",
                    "url_token": "sample-author",
                    "name": "样例作者",
                },
            )
        return handler(request)

    url = (
        "https://www.zhihu.com/question/100/answer/1000"
        if mode == "question"
        else "https://www.zhihu.com/people/sample-author/answers"
    )
    result = ZhihuWebService(transport=httpx.MockTransport(site), sleep=sleep).preview(
        ZhihuWebPreviewRequest(url=url, mode=mode, **options),
        cookie=cookie,
    )
    return result, calls


def test_question_preview_sorts_only_fetched_matches_and_preserves_provenance():
    result, calls = preview(
        lambda _: page(
            [
                answer("1000", voteup_count=130),
                answer("1001", voteup_count=500),
                answer("1002", voteup_count=99),
            ]
        )
    )
    assert [item.answer_id for item in result.items] == ["1001", "1000"]
    assert result.scanned_count == 3 and result.skipped_count == 1
    assert result.pages_fetched == 1 and not result.has_more
    assert result.stop_reason == "exhausted" and result.target_label == "共同问题"
    assert "不保证" in result.warning and "已读取" in result.warning
    assert calls[-1].url.params["sort_by"] == "default"
    source = result.items[0].draft
    assert source.title == "共同问题" and source.content_extent == "fulltext"
    assert source.author_id == "zhihu-author:stable-author"
    assert source.provenance.external_author_id == "stable-author"
    assert source.provenance.external_id == "1001"
    assert source.provenance.content_hash == hashlib.sha256(source.text.encode()).hexdigest()
    assert str(source.url) == "https://www.zhihu.com/question/100/answer/1001"
    assert source.topics == ["知乎问题:100"]
    assert "<p>" not in source.text and "第二段" in source.text


def test_author_answers_across_questions_share_actual_member_id():
    result, calls = preview(
        lambda _: page(
            [
                answer("1000", qid="100"),
                answer("1001", qid="200"),
            ],
            path=AUTHOR_PATH,
        ),
        mode="author",
    )
    assert len(result.items) == 2
    assert {item.question_id for item in result.items} == {"100", "200"}
    assert {item.draft.author_id for item in result.items} == {"zhihu-author:stable-author"}
    assert {item.draft.title for item in result.items} == {"问题 100", "问题 200"}
    assert calls[-1].url.params["sort_by"] == "voteups"
    assert result.target_label == "样例作者"


@pytest.mark.parametrize(
    "mode,wrong",
    [
        ("question", answer("1002", qid="999")),
        ("author", answer("1002", author_id="someone-else")),
        ("author", answer("1002", author_id=None)),
    ],
)
def test_mixed_scope_page_cannot_import_a_valid_looking_subset(mode, wrong):
    path = QUESTION_PATH if mode == "question" else AUTHOR_PATH
    result, _ = preview(lambda _: page([answer(), wrong], path=path), mode=mode)
    assert result.items == [] and result.stop_reason == "scope_mismatch"
    assert result.scanned_count == result.skipped_count == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"is_normal": None},
        {"is_normal": False},
        {"is_deleted": True},
        {"paid_info": {"paid_type": "paid"}},
        {"paidInfo": {"paid_type": "paid"}},
        {"is_paid": True},
        {"is_truncated": True},
        {"content_truncated": True},
        {"content": None, "excerpt": "只有摘要"},
        {"content": "<script>secret()</script>"},
        {"voteup_count": "999"},
        {"content": "a" * 100_001},
    ],
)
def test_incomplete_invalid_or_oversized_content_is_never_upgraded(changes):
    result, _ = preview(lambda _: page([answer(**changes)]))
    assert not result.items and result.skipped_count == 1


def test_anonymous_authors_stay_answer_scoped_and_unknown_votes_do_not_pass_threshold():
    rows = [
        answer("1000", author_id="0"),
        answer("1001", author_id=None),
        answer("1002", voteup_count=None),
    ]
    result, _ = preview(lambda _: page(rows))
    assert [item.draft.author_id for item in result.items] == [
        "zhihu-answer:1000",
        "zhihu-answer:1001",
    ]
    assert all(item.draft.provenance.external_author_id is None for item in result.items)
    assert result.skipped_count == 1


def test_pagination_deduplicates_ids_and_identical_text_and_sleeps_between_requests():
    delays = []

    def handler(request):
        if request.url.params["offset"] == "0":
            return page([answer()], offset=20)
        return page([answer(), answer("1001", content=answer()["content"]), answer("1002")])

    result, calls = preview(handler, sleep=delays.append)
    assert [item.answer_id for item in result.items] == ["1000", "1002"]
    assert result.scanned_count == 4 and result.skipped_count == 2
    assert result.pages_fetched == 2 and len(calls) == 3
    assert delays == [1.0, 1.0]
    assert calls[-1].url.params["offset"] == "20"


@pytest.mark.parametrize(
    "status,stop",
    [
        (401, "login_required"),
        (403, "access_denied"),
        (429, "rate_limited"),
        (302, "redirect_requires_browser"),
    ],
)
def test_access_stops_retain_earlier_pages_without_retries_or_response_leaks(status, stop):
    def handler(request):
        if request.url.params["offset"] == "0":
            return page([answer()], offset=20)
        return httpx.Response(
            status, text="do-not-echo-server-secret", headers={"Location": "https://evil.example"}
        )

    result, calls = preview(handler)
    assert len(result.items) == 1 and result.stop_reason == stop and result.has_more
    assert len(calls) == 3 and all(request.url.host == "www.zhihu.com" for request in calls)
    assert "do-not-echo" not in result.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/api/v4/questions/100/answers?offset=20",
        "https://www.zhihu.com/api/v4/questions/999/answers?offset=20",
        "https://www.zhihu.com/api/v4/members/sample-author/answers?offset=20",
        "https://user:secret@www.zhihu.com/api/v4/questions/100/answers?offset=20",
        "https://www.zhihu.com:444/api/v4/questions/100/answers?offset=20",
        "https://www.zhihu.com/api/v4/questions/100/answers?offset=20&offset=40",
        "https://www.zhihu.com/api/v4/questions/100/answers?offset=-1",
    ],
)
def test_untrusted_pagination_never_sends_a_third_request(url):
    result, calls = preview(
        lambda _: httpx.Response(
            200,
            json={
                "data": [answer()],
                "paging": {"is_end": False, "next": url},
            },
        )
    )
    assert result.items == [] and result.stop_reason == "unsafe_pagination"
    assert result.scanned_count == result.skipped_count == 1
    assert len(calls) == 2


def test_repeated_page_stops_and_preserves_prior_results():
    result, calls = preview(
        lambda request: page(
            [answer()],
            offset=int(request.url.params["offset"]) + 20,
        )
    )
    assert len(result.items) == 1 and result.stop_reason == "pagination_stalled"
    assert len(calls) == 3 and result.skipped_count == 1


@pytest.mark.parametrize(
    "url,mode",
    [
        ("https://evil.example/question/100", "question"),
        ("https://www.zhihu.com.evil.example/question/100", "question"),
        ("https://user:password@www.zhihu.com/question/100", "question"),
        ("http://www.zhihu.com/question/100", "question"),
        ("https://www.zhihu.com:443/question/100", "question"),
        ("https://www.zhihu.com/question/%31%30%30", "question"),
        ("https://www.zhihu.com/question/100\n", "author"),
        ("https://www.zhihu.com/question/100", "author"),
        ("https://www.zhihu.com/people/../api", "author"),
        ("https://www.zhihu.com/people/a%2fb", "author"),
    ],
)
def test_invalid_targets_fail_before_network_access(url, mode):
    def unexpected(_):
        pytest.fail("invalid target reached network")

    with pytest.raises(DomainError) as exc:
        ZhihuWebService(transport=httpx.MockTransport(unexpected)).preview(
            ZhihuWebPreviewRequest(url=url, mode=mode),
        )
    assert exc.value.code == "zhihu_web_invalid_url" and exc.value.status == 422


def test_secret_echo_is_rejected_before_any_content_or_label_is_returned():
    cookie = "z_c0=private-session-secret; test=123"
    result, calls = preview(
        lambda _: page(
            [
                answer(content="<p>private-session-secret</p>"),
            ]
        ),
        cookie=cookie,
    )
    assert result.stop_reason == "sensitive_response" and not result.items
    assert "private-session-secret" not in result.model_dump_json()
    assert all(request.headers["cookie"] == cookie for request in calls)


@pytest.mark.parametrize(
    "content",
    [
        '<p>session="synthetic-quoted-cookie-123"</p>',
        "<p>session=&quot;synthetic-quoted-cookie-123&quot;</p>",
        '<p>session="synthetic-<script>hidden</script>quoted-cookie-123"</p>',
        "<p>synthetic-quoted-cookie-123</p>",
    ],
)
def test_quoted_or_html_encoded_cookie_echo_cannot_become_an_imported_source(content):
    result, _ = preview(
        lambda _: page([answer(content=content)]), cookie='session="synthetic-quoted-cookie-123"'
    )
    assert result.stop_reason == "sensitive_response" and not result.items
    assert "synthetic-quoted-cookie" not in result.model_dump_json()


def test_cookie_echo_formed_by_title_html_removal_is_not_returned_as_target_label():
    def handler(_):
        return httpx.Response(
            200,
            json={
                "id": 100,
                "title": "synthetic-<script>hidden</script>session-secret",
            },
        )

    result = ZhihuWebService(transport=httpx.MockTransport(handler)).preview(
        ZhihuWebPreviewRequest(url="https://www.zhihu.com/question/100", mode="question"),
        cookie="session=synthetic-session-secret",
    )
    assert result.stop_reason == "sensitive_response"
    assert "synthetic-session-secret" not in result.model_dump_json()


@pytest.mark.parametrize("cookie", ["a=b\r\nX-Evil: yes", "a=\x7f", "a=中文", "a" * 16385])
def test_invalid_cookie_is_rejected_with_sanitized_domain_error(cookie):
    with pytest.raises(DomainError) as exc:
        preview(lambda _: page([]), cookie=cookie)
    assert exc.value.code == "zhihu_web_invalid_cookie"
    assert cookie not in str(exc.value)


def test_page_limit_does_not_claim_all_matching_answers_were_seen():
    def handler(request):
        offset = int(request.url.params["offset"])
        return page([answer(str(1000 + offset), voteup_count=10)], offset=offset + 20)

    result, calls = preview(handler)
    assert result.stop_reason == "page_limit" and result.has_more
    assert not result.items and result.pages_fetched == 10 and len(calls) == 11
    assert result.scanned_count == result.skipped_count == 10


def test_requested_count_returns_highest_votes_in_fetched_page():
    result, calls = preview(
        lambda _: page(
            [
                answer("1000", voteup_count=150),
                answer("1001", voteup_count=500),
                answer("1002", voteup_count=200),
            ]
        ),
        max_items=2,
    )
    assert [item.answer_id for item in result.items] == ["1001", "1002"]
    assert result.stop_reason == "max_items" and result.has_more
    assert len(calls) == 2 and result.skipped_count == 1


def test_deadline_stops_before_another_request(monkeypatch):
    monkeypatch.setattr(web_service, "MAX_SECONDS", 0.5)
    result, calls = preview(lambda _: page([answer()]))
    assert result.stop_reason == "deadline" and not result.items
    assert len(calls) == 1


def test_oversized_response_and_html_challenge_return_sanitized_stops(monkeypatch):
    monkeypatch.setattr(web_service, "MAX_RESPONSE_BYTES", 500)
    large, _ = preview(lambda _: page([answer(content="x" * 2000)]))
    assert large.stop_reason == "response_too_large" and not large.items
    challenge, _ = preview(
        lambda _: httpx.Response(200, text="<html>private challenge token</html>")
    )
    assert challenge.stop_reason == "browser_required"
    assert "private challenge token" not in challenge.model_dump_json()


def test_author_metadata_must_resolve_the_requested_profile():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"id": "different-author", "url_token": "other-slug", "name": "其他人"}
        )

    result = ZhihuWebService(transport=httpx.MockTransport(handler), sleep=lambda _: None).preview(
        ZhihuWebPreviewRequest(url="https://www.zhihu.com/org/sample-author", mode="author"),
    )
    assert result.stop_reason == "scope_mismatch" and not result.items and len(calls) == 1


def test_network_errors_never_echo_request_credentials():
    def handler(request):
        raise httpx.ConnectError("private-cookie-network-detail", request=request)

    result, _ = preview(handler)
    assert result.stop_reason == "web_network_error"
    assert "private-cookie" not in json.dumps(result.model_dump(mode="json"))
