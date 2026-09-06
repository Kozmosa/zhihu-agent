"""模型只声明概念、关系与服务提供的证据编号。"""

from typing import Annotated

from pydantic import Field

from zhijing.domain.models import NonBlank, Schema
from zhijing.features.knowledge.schemas import Relation

Identifier = Annotated[NonBlank, Field(max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
Label = Annotated[NonBlank, Field(max_length=200)]
Explanation = Annotated[NonBlank, Field(max_length=2000)]
EvidenceIds = Annotated[list[Identifier], Field(min_length=1, max_length=30)]


class GeneratedNode(Schema):
    id: Identifier
    label: Label
    description: Explanation
    evidence_ids: EvidenceIds


class GeneratedEdge(Schema):
    id: Identifier
    source: Identifier
    target: Identifier
    relation: Relation
    explanation: Explanation
    evidence_ids: EvidenceIds


class GeneratedGraph(Schema):
    nodes: list[GeneratedNode] = Field(min_length=1, max_length=100)
    edges: list[GeneratedEdge] = Field(max_length=200)
