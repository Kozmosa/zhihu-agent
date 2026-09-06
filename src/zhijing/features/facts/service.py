from zhijing.core.text import chunks
from zhijing.domain.citations import cite
from zhijing.domain.ports import Retriever, SourceRepository
from zhijing.features.facts.schemas import ClaimReview, FactRequest, FactResult


class FactService:
    def __init__(self, repository: SourceRepository, retriever: Retriever):
        self.repository = repository
        self.retriever = retriever

    def review(self, request: FactRequest) -> FactResult:
        excluded = set(request.exclude_source_ids)
        sources = [s for s in self.repository.list(request.author_id) if s.id not in excluded]
        reviews = []
        for claim in request.claims:
            exact = []
            for source in sources:
                for index, passage in enumerate(chunks(source.text)):
                    if claim in passage:
                        exact.append(cite(source, index, passage, 1))
            if exact:
                status, explanation, evidence = (
                    "mentioned_in_corpus",
                    "语料中出现相同表述，尚未验证真实性。",
                    exact[:5],
                )
            else:
                evidence = [
                    c
                    for c in self.retriever.search(claim, request.author_id, 100)
                    if c.source_id not in excluded
                ][:5]
                status = "related_evidence" if evidence else "insufficient_evidence"
                explanation = (
                    "找到词汇相关片段，可能支持、反驳或无关，需人工核对。"
                    if evidence
                    else "未找到依据；不能据此断言该主张为假。"
                )
            reviews.append(
                ClaimReview(
                    claim=claim,
                    status=status,
                    explanation=explanation,
                    evidence=evidence,
                )
            )
        return FactResult(reviews=reviews)
