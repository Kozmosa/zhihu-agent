"""模型仅返回受限的证据编号和语义判断，来源由服务回填。"""

from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import NonBlank, Schema

Reason = Annotated[NonBlank, Field(max_length=4000)]


class GeneratedAssessment(Schema):
    evidence_id: Annotated[NonBlank, Field(max_length=30)]
    relation: Literal["supports", "refutes", "context"]
    rationale: Reason


class GeneratedReview(Schema):
    verdict: Literal["supported", "refuted", "mixed", "insufficient"]
    explanation: Reason
    assessments: list[GeneratedAssessment] = Field(max_length=10)
    conditions: list[Reason] = Field(default_factory=list, max_length=10)
