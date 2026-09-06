import copy

import pytest

from zhijing.core.errors import DomainError
from zhijing.domain.models import SourceDraft
from zhijing.features.facts.schemas import FactRequest
from zhijing.features.facts.service import FactService


class StubGenerator:
    def __init__(self, response):
        self.response, self.calls = response, []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["response_model"].model_validate(self.response)


@pytest.fixture
def setup(client):
    base = client.app.state.container.facts
    sources = [
        base.repository.save(
            SourceDraft(
                title=f"研究{index}",
                author_id=author,
                author_name=author,
                text=text,
            )
        )
        for index, (author, text) in enumerate(
            [
                ("alice", "主动回忆可以帮助学习。"),
                ("alice", "主动回忆不能帮助学习。"),
                ("bob", "主动回忆只是一种学习方法。"),
            ]
        )
    ]
    return base, sources


def decision(verdict="supported", ids=("e1",), relations=("supports",)):
    return {
        "verdict": verdict,
        "explanation": "根据现有资料判断，不能证明客观事实。",
        "assessments": [
            {"evidence_id": key, "relation": relation, "rationale": "原文表达了此观点。"}
            for key, relation in zip(ids, relations, strict=True)
        ],
        "conditions": ["仅限当前导入资料"],
    }


@pytest.mark.parametrize(
    "verdict,ids,relations,status",
    [
        ("supported", ("e1",), ("supports",), "supported_by_evidence"),
        ("refuted", ("e2",), ("refutes",), "refuted_by_evidence"),
        ("mixed", ("e1", "e2"), ("supports", "refutes"), "mixed_evidence"),
        ("insufficient", ("e1",), ("context",), "insufficient_evidence"),
    ],
)
def test_semantic_review_uses_real_citations(setup, verdict, ids, relations, status):
    base, sources = setup
    generator = StubGenerator(decision(verdict, ids, relations))
    result = FactService(base.repository, base.retriever, generator).review(
        FactRequest(claims=[sources[0].text], author_id="alice")
    )
    review = result.reviews[0]
    assert result.mode == "ollama" and review.status == status
    assert "不代表客观真实性证明" in result.analysis_notice
    assert generator.calls[0]["task"] == "facts"
    for analysis in review.evidence_analysis:
        source = base.repository.get(analysis.citation.source_id)
        assert source.author_id == "alice"
        assert analysis.citation.excerpt in source.text
    assert set(item.source_id for item in review.evidence) <= {s.id for s in sources[:2]}


@pytest.mark.parametrize(
    "response",
    [
        decision(ids=("made-up",)),
        decision(ids=("e1", "e1"), relations=("supports", "supports")),
        decision(verdict="mixed"),
        decision(verdict="insufficient"),
        decision(ids=(), relations=()),
    ],
)
def test_invalid_citation_or_inconsistent_verdict_is_rejected(setup, response):
    base, sources = setup
    service = FactService(base.repository, base.retriever, StubGenerator(copy.deepcopy(response)))
    with pytest.raises(DomainError) as error:
        service.review(FactRequest(claims=[sources[0].text], author_id="alice"))
    assert error.value.code == "model_invalid_response" and error.value.status == 502


def test_excluded_and_other_authors_never_reach_model(setup):
    base, sources = setup
    generator = StubGenerator(decision(verdict="refuted", relations=("refutes",)))
    result = FactService(base.repository, base.retriever, generator).review(
        FactRequest(
            claims=[sources[0].text],
            author_id="alice",
            exclude_source_ids=[sources[0].id],
        )
    )
    supplied = generator.calls[0]["payload"]["evidence"]
    assert {item["source_id"] for item in supplied} == {sources[1].id}
    assert result.reviews[0].evidence[0].source_id == sources[1].id


@pytest.mark.parametrize("author,claim", [("nobody", "主动回忆"), ("alice", "xyz987654")])
def test_no_evidence_does_not_call_model(setup, author, claim):
    base, _ = setup
    generator = StubGenerator({})
    result = FactService(base.repository, base.retriever, generator).review(
        FactRequest(claims=[claim], author_id=author)
    )
    assert not generator.calls
    assert result.reviews[0].status == "insufficient_evidence"
    assert result.mode == "extractive"
