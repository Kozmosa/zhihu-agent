import hashlib
from collections import Counter

from zhijing.core.errors import DomainError
from zhijing.core.text import chunks
from zhijing.domain.citations import cite
from zhijing.domain.ports import SourceRepository, StructuredGenerator
from zhijing.features.knowledge.generation import build_model_graph
from zhijing.features.knowledge.schemas import (
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeData,
    Position,
    SourceExtentCounts,
)


class KnowledgeService:
    def __init__(
        self,
        repository: SourceRepository,
        generator: StructuredGenerator | None = None,
    ):
        self.repository = repository
        self.generator = generator

    def build(
        self,
        author_id: str | None = None,
        limit: int = 100,
        primary_source_id: str | None = None,
    ) -> KnowledgeGraph:
        sources = self.repository.list(author_id)
        ordered = sources
        if primary_source_id is not None:
            primary = next((source for source in sources if source.id == primary_source_id), None)
            if primary is None:
                raise DomainError("source_not_found", "所选资料不在当前地图范围内。", 404)
            ordered = [primary, *(source for source in sources if source.id != primary_source_id)]
        selected = ordered[:limit]
        if self.generator and selected:
            return build_model_graph(self.generator, selected, len(sources))
        nodes, edges, topics = [], [], {}
        for index, source in enumerate(selected):
            answer_id = f"answer:{source.id}"
            nodes.append(
                GraphNode(
                    id=answer_id,
                    position=Position(x=360, y=index * 100),
                    data=NodeData(
                        label=source.title,
                        kind="answer",
                        source_id=source.id,
                        content_extent=source.content_extent,
                        evidence=[cite(source, 0, chunks(source.text)[0], 1)],
                    ),
                )
            )
            for topic in sorted(set(source.topics or ["未分类"])):
                if topic not in topics:
                    topic_id = "topic:" + hashlib.sha256(topic.encode()).hexdigest()[:16]
                    nodes.append(
                        GraphNode(
                            id=topic_id,
                            position=Position(x=0, y=len(topics) * 150),
                            data=NodeData(label=topic, kind="topic"),
                        )
                    )
                    topics[topic] = topic_id
                edges.append(
                    GraphEdge(
                        id=f"{topics[topic]}->{answer_id}",
                        source=topics[topic],
                        target=answer_id,
                    )
                )
        return KnowledgeGraph(
            nodes=nodes,
            edges=edges,
            total_sources=len(sources),
            truncated=len(sources) > limit,
            included_sources=len(selected),
            content_extent_counts=SourceExtentCounts(
                **Counter(source.content_extent for source in selected)
            ),
            analysis_notice=(
                "节点和连线表达资料组织方式，不代表已验证的客观事实。"
                "资料节点仅展示正文节选；完整性标记沿用导入信息，未核验原网页是否完整。"
            ),
        )
