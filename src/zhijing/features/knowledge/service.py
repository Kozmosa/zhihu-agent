import hashlib

from zhijing.domain.ports import SourceRepository
from zhijing.features.knowledge.schemas import (
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeData,
    Position,
)


class KnowledgeService:
    def __init__(self, repository: SourceRepository):
        self.repository = repository

    def build(self, author_id: str | None = None, limit: int = 100) -> KnowledgeGraph:
        sources = self.repository.list(author_id)
        nodes, edges, topics = [], [], {}
        for index, source in enumerate(sources[:limit]):
            answer_id = f"answer:{source.id}"
            nodes.append(
                GraphNode(
                    id=answer_id,
                    position=Position(x=360, y=index * 100),
                    data=NodeData(label=source.title, kind="answer", source_id=source.id),
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
        )
