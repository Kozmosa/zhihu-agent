from typing import Literal

from pydantic import Field

from zhijing.domain.models import Citation, Schema

Relation = Literal["supports", "refutes", "related", "prerequisite", "qualifies", "supplements"]


class Position(Schema):
    x: float
    y: float


class NodeData(Schema):
    label: str
    kind: Literal["topic", "answer", "concept"]
    source_id: str | None = None
    description: str | None = None
    evidence: list[Citation] = Field(default_factory=list)


class GraphNode(Schema):
    id: str
    position: Position
    data: NodeData


class GraphEdge(Schema):
    id: str
    source: str
    target: str
    label: str = "归类"
    data: "EdgeData | None" = None


class EdgeData(Schema):
    relation: Relation
    explanation: str
    evidence: list[Citation]


class KnowledgeGraph(Schema):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_sources: int
    truncated: bool
    mode: Literal["extractive", "ollama", "openai"] = "extractive"
    classification: str = "按导入的 topics 标签分组；未标注归入未分类。"
    analysis_notice: str = "节点和连线表达资料组织方式，不代表已验证的客观事实。"
