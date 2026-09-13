from types import SimpleNamespace

import pytest

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source
from zhijing.features.knowledge.service import KnowledgeService


def source(identifier, extent, *, author="alice", text="已导入的合成资料。"):
    return Source(
        id=identifier,
        title=f"资料{identifier}",
        author_id=author,
        author_name="合成作者",
        text=text,
        url=f"https://example.test/{identifier}",
        content_extent=extent,
        created_at="2026-09-13T00:00:00Z",
    )


def repository(sources):
    return SimpleNamespace(
        list=lambda author: [s for s in sources if author is None or s.author_id == author]
    )


class EmptyGraphGenerator:
    mode = "openai"

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["response_model"].model_validate({"nodes": [], "edges": []})


@pytest.mark.parametrize("use_model", [False, True])
def test_scope_counts_use_only_included_sources_even_when_no_concepts(use_model):
    sources = [source("a", "fulltext"), source("b", "excerpt"), source("c", "unknown")]
    generator = EmptyGraphGenerator() if use_model else None
    result = KnowledgeService(repository(sources), generator).build(limit=2)
    assert result.total_sources == 3 and result.included_sources == 2 and result.truncated
    assert result.content_extent_counts.model_dump() == {"fulltext": 1, "excerpt": 1, "unknown": 0}
    if generator:
        assert not result.nodes
        supplied = generator.calls[0]["payload"]["sources"]
        assert {item["source_id"]: item["content_extent"] for item in supplied} == {
            "a": "fulltext",
            "b": "excerpt",
        }
        assert "不要将摘要" in generator.calls[0]["instructions"]
        assert "完整原文" not in result.analysis_notice and "未核验" in result.analysis_notice


def test_offline_nodes_have_contiguous_bounded_excerpt_and_no_invented_relations():
    original = "  第一段。\n" + "这是连续正文。" * 180
    item = source("a", "excerpt", text=original)
    result = KnowledgeService(repository([item])).build()
    answer = next(node for node in result.nodes if node.data.kind == "answer")
    topic = next(node for node in result.nodes if node.data.kind == "topic")
    assert answer.data.content_extent == "excerpt"
    citation = answer.data.evidence[0]
    assert citation.excerpt == original[: len(citation.excerpt)]
    assert 0 < len(citation.excerpt) <= 600
    assert citation.source_id == item.id and citation.url == str(item.url)
    assert citation.chunk_index == 0
    assert topic.data.label == "未分类" and topic.data.evidence == []
    assert result.edges[0].label == "归类" and result.edges[0].data is None
    assert "正文节选" in result.analysis_notice


def test_empty_scope_reports_zero_counts_without_generation():
    generator = EmptyGraphGenerator()
    result = KnowledgeService(repository([]), generator).build()
    assert not generator.calls and result.included_sources == result.total_sources == 0
    assert result.content_extent_counts.model_dump() == {"fulltext": 0, "excerpt": 0, "unknown": 0}


@pytest.mark.parametrize("use_model", [False, True])
def test_primary_outside_original_limit_is_included_without_changing_scope(use_model):
    sources = [source("a", "fulltext"), source("b", "excerpt"), source("c", "unknown")]
    generator = EmptyGraphGenerator() if use_model else None
    service = KnowledgeService(repository(sources), generator)
    default = service.build("alice", limit=1)
    assert default.content_extent_counts.fulltext == 1
    result = service.build("alice", limit=1, primary_source_id="c")
    assert result.total_sources == 3 and result.included_sources == 1 and result.truncated
    assert result.content_extent_counts.model_dump() == {"fulltext": 0, "excerpt": 0, "unknown": 1}
    if generator:
        assert [item["source_id"] for item in generator.calls[-1]["payload"]["sources"]] == ["c"]
    else:
        assert [node.data.source_id for node in result.nodes if node.data.kind == "answer"] == ["c"]


@pytest.mark.parametrize("primary", ["missing", "bob-source"])
def test_primary_cannot_escape_author_scope(primary):
    sources = [source("a", "fulltext"), source("bob-source", "unknown", author="bob")]
    generator = EmptyGraphGenerator()
    with pytest.raises(DomainError) as error:
        KnowledgeService(repository(sources), generator).build("alice", primary_source_id=primary)
    assert error.value.code == "source_not_found" and error.value.status == 404
    assert not generator.calls


def test_route_accepts_primary_and_returns_included_scope(client, imported):
    primary = imported[-1]
    response = client.get(
        "/api/v1/knowledge-map", params={"primary_source_id": primary["id"], "limit": 1}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["included_sources"] == 1
    assert [
        node["data"]["source_id"] for node in result["nodes"] if node["data"]["kind"] == "answer"
    ] == [primary["id"]]
    rejected = client.get(
        "/api/v1/knowledge-map",
        params={"primary_source_id": primary["id"], "author_id": "missing-author"},
    )
    assert rejected.status_code == 404
