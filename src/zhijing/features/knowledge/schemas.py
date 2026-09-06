from typing import Literal

from zhijing.domain.models import Schema


class Position(Schema):
    x: float
    y: float


class NodeData(Schema):
    label: str
    kind: Literal["topic", "answer"]
    source_id: str | None = None


class GraphNode(Schema):
    id: str
    position: Position
    data: NodeData


class GraphEdge(Schema):
    id: str
    source: str
    target: str
    label: str = "归类"


class KnowledgeGraph(Schema):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_sources: int
    truncated: bool
    classification: str = "按导入的 topics 标签分组；未标注归入未分类。"
