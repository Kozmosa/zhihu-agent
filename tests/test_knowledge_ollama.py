import copy

import pytest

from zhijing.core.errors import DomainError
from zhijing.domain.models import SourceDraft
from zhijing.features.knowledge.service import KnowledgeService


class StubGenerator:
    def __init__(self, response):
        self.response, self.calls = response, []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["response_model"].model_validate(self.response)


@pytest.fixture
def setup(client):
    repository = client.app.state.runtime.current.container.knowledge.repository
    sources = [
        repository.save(
            SourceDraft(
                title=f"知识{index}",
                author_id=author,
                author_name=author,
                text=text,
            )
        )
        for index, (author, text) in enumerate(
            [
                ("alice", "点积是理解注意力机制的前置知识。"),
                ("alice", "注意力机制使用点积衡量向量之间的关系。"),
                ("bob", "这些资料不属于当前作者。"),
            ]
        )
    ]
    return repository, sources


@pytest.fixture
def graph():
    return {
        "nodes": [
            {
                "id": "dot",
                "label": "点积",
                "description": "向量间的一种运算。",
                "evidence_ids": ["e1"],
            },
            {
                "id": "attention",
                "label": "注意力机制",
                "description": "使用点积计算关系。",
                "evidence_ids": ["e2"],
            },
        ],
        "edges": [
            {
                "id": "r1",
                "source": "dot",
                "target": "attention",
                "relation": "prerequisite",
                "explanation": "原文说明前置关系。",
                "evidence_ids": ["e1"],
            }
        ],
    }


def test_model_graph_has_traceable_concepts_and_relations(setup, graph):
    repository, sources = setup
    generator = StubGenerator(graph)
    result = KnowledgeService(repository, generator).build("alice")
    assert result.mode == "ollama" and not result.truncated
    assert result.total_sources == 2
    assert result.edges[0].data.relation == "prerequisite"
    node_ids = {node.id for node in result.nodes}
    assert result.edges[0].source in node_ids and result.edges[0].target in node_ids
    evidence = generator.calls[0]["payload"]["evidence"]
    assert {item["source_id"] for item in evidence} == {source.id for source in sources[:2]}
    assert generator.calls[0]["task"] == "knowledge"
    for node in result.nodes:
        assert node.data.kind == "concept"
        for citation in node.data.evidence:
            assert citation.excerpt in repository.get(citation.source_id).text
    for edge in result.edges:
        assert edge.data.evidence[0].excerpt in repository.get(edge.data.evidence[0].source_id).text


@pytest.mark.parametrize(
    "mutation",
    [
        "node_evidence",
        "edge_evidence",
        "dangling",
        "self_edge",
        "node_duplicate",
        "edge_duplicate",
        "evidence_duplicate",
    ],
)
def test_invalid_graph_is_rejected(setup, graph, mutation):
    repository, _ = setup
    bad = copy.deepcopy(graph)
    if mutation == "node_evidence":
        bad["nodes"][0]["evidence_ids"] = ["fabricated"]
    elif mutation == "edge_evidence":
        bad["edges"][0]["evidence_ids"] = ["fabricated"]
    elif mutation == "dangling":
        bad["edges"][0]["target"] = "missing"
    elif mutation == "self_edge":
        bad["edges"][0]["target"] = "dot"
    elif mutation == "node_duplicate":
        bad["nodes"].append(copy.deepcopy(bad["nodes"][0]))
    elif mutation == "edge_duplicate":
        bad["edges"].append(copy.deepcopy(bad["edges"][0]))
    else:
        bad["nodes"][0]["evidence_ids"] = ["e1", "e1"]
    with pytest.raises(DomainError) as error:
        KnowledgeService(repository, StubGenerator(bad)).build("alice")
    assert error.value.code == "model_invalid_response" and error.value.status == 502


def test_empty_library_does_not_call_model(setup):
    repository, _ = setup
    generator = StubGenerator({})
    result = KnowledgeService(repository, generator).build("nobody")
    assert not generator.calls and not result.nodes and not result.edges
    assert result.total_sources == 0 and result.mode == "extractive"


def test_source_limit_is_explicit_and_selected_text_is_complete(setup, graph):
    repository, sources = setup
    for node in graph["nodes"]:
        node["evidence_ids"] = ["e1"]
    generator = StubGenerator(graph)
    result = KnowledgeService(repository, generator).build("alice", limit=1)
    assert result.truncated and result.total_sources == 2
    evidence = generator.calls[0]["payload"]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["excerpt"] == repository.get(evidence[0]["source_id"]).text
    assert evidence[0]["source_id"] in {source.id for source in sources[:2]}
