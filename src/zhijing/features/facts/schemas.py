from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import Citation, NonBlank, Schema, ShortText


class FactRequest(Schema):
    claims: list[Annotated[NonBlank, Field(max_length=2000)]] = Field(min_length=1, max_length=20)
    author_id: ShortText | None = None
    exclude_source_ids: list[ShortText] = Field(default_factory=list, max_length=20)


class ClaimReview(Schema):
    claim: str
    status: Literal[
        "mentioned_in_corpus",
        "related_evidence",
        "insufficient_evidence",
        "supported_by_evidence",
        "refuted_by_evidence",
        "mixed_evidence",
    ]
    explanation: str
    evidence: list[Citation]
    conditions: list[str] = Field(default_factory=list)
    evidence_analysis: list["EvidenceAnalysis"] = Field(default_factory=list)


class EvidenceAnalysis(Schema):
    evidence_id: str
    relation: Literal["supports", "refutes", "context"]
    rationale: str
    citation: Citation


class FactResult(Schema):
    reviews: list[ClaimReview]
    mode: Literal["extractive", "ollama"] = "extractive"
    scope: str = "仅审查已导入语料。文本出现、相似度和作者观点均不能证明客观事实。"
    analysis_notice: str = "审查结果仅描述当前语料与主张的关系，不代表独立的客观真实性证明。"
