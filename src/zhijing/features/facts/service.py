from zhijing.core.text import chunks
from zhijing.domain.citations import cite
from zhijing.domain.ports import Retriever, SourceRepository, StructuredGenerator
from zhijing.features.facts.generation import analyze_claim
from zhijing.features.facts.schemas import ClaimReview, FactRequest, FactResult


class FactService:
    def __init__(
        self,
        repository: SourceRepository,
        retriever: Retriever,
        generator: StructuredGenerator | None = None,
    ):
        self.repository = repository
        self.retriever = retriever
        self.generator = generator

    def review(self, request: FactRequest) -> FactResult:
        excluded = set(request.exclude_source_ids)
        sources = [s for s in self.repository.list(request.author_id) if s.id not in excluded]
        allowed = {source.id: source for source in sources}
        reviews = []
        model_used = False
        for claim in request.claims:
            exact = []
            for source in sources:
                for index, passage in enumerate(chunks(source.text)):
                    if claim in passage:
                        exact.append(cite(source, index, passage, 1))
            # Enforce scope at this boundary even if a retriever implementation misbehaves.
            related = [
                item
                for item in self.retriever.search(claim, request.author_id, 100)
                if item.source_id in allowed
                and item.excerpt
                and item.excerpt in allowed[item.source_id].text
            ]
            if self.generator:
                unique = {}
                for item in exact + related:
                    key = (item.source_id, item.chunk_index, item.excerpt)
                    source = allowed[item.source_id]
                    unique.setdefault(key, cite(source, item.chunk_index, item.excerpt, item.score))
                evidence = list(unique.values())[:10]
                if evidence:
                    reviews.append(analyze_claim(self.generator, claim, evidence))
                    model_used = True
                    continue
            if exact:
                status, explanation, evidence = (
                    "mentioned_in_corpus",
                    "语料中出现相同表述，尚未验证真实性。",
                    exact[:5],
                )
            else:
                evidence = related[:5]
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
        return FactResult(
            reviews=reviews,
            mode=getattr(self.generator, "mode", "ollama") if model_used else "extractive",
            analysis_notice=(
                "模型分析仅判断检索证据与主张的语义关系，可能有误；不代表客观真实性证明。"
                if model_used
                else "规则匹配仅提示文本出现或相关性，不代表客观真实性证明。"
            ),
        )
