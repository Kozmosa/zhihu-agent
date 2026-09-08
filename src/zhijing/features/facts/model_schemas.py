"""模型仅返回受限的证据编号和语义判断，来源由服务回填。"""

from typing import Annotated, Literal

from pydantic import Field

from zhijing.core.output_policy import (
    FACT_CONDITION_MAX,
    FACT_CONDITIONS_MAX,
    FACT_EXPLANATION_MAX,
    FACT_RATIONALE_MAX,
)
from zhijing.domain.models import NonBlank, Schema

Explanation = Annotated[
    NonBlank,
    Field(
        max_length=FACT_EXPLANATION_MAX,
        description=(
            "先给限定在当前语料内的结论，再说明证据理由、适用条件和未知边界；"
            f"不作全网真伪认证，不超过 {FACT_EXPLANATION_MAX} 字符。"
        ),
    ),
]
Rationale = Annotated[
    NonBlank,
    Field(
        max_length=FACT_RATIONALE_MAX,
        description=(
            "简要解释这条证据为何支持、反驳或仅提供背景，保留原文中的限定；"
            f"不超过 {FACT_RATIONALE_MAX} 字符。"
        ),
    ),
]
Condition = Annotated[
    NonBlank,
    Field(
        max_length=FACT_CONDITION_MAX,
        description=f"仅写已有证据中的适用条件或边界，不超过 {FACT_CONDITION_MAX} 字符。",
    ),
]


class GeneratedAssessment(Schema):
    evidence_id: Annotated[NonBlank, Field(max_length=30)]
    relation: Literal["supports", "refutes", "context"]
    rationale: Rationale


class GeneratedReview(Schema):
    verdict: Literal["supported", "refuted", "mixed", "insufficient"]
    explanation: Explanation
    assessments: list[GeneratedAssessment] = Field(max_length=10)
    conditions: list[Condition] = Field(
        default_factory=list,
        max_length=FACT_CONDITIONS_MAX,
        description=f"按重要性列出证据中的适用条件，避免重复，最多 {FACT_CONDITIONS_MAX} 条。",
    )
