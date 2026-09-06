from zhijing.core.errors import DomainError
from zhijing.core.text import chunks, sentences
from zhijing.domain.ports import SourceRepository
from zhijing.features.reader.schemas import ReadingRequest, ReadingResult, Section


class ReaderService:
    def __init__(self, repository: SourceRepository):
        self.repository = repository

    def analyze(self, request: ReadingRequest) -> ReadingResult:
        text = request.text
        if request.source_id:
            source = self.repository.get(request.source_id)
            if source is None:
                raise DomainError("source_not_found", "待拆解资料不存在。", 404)
            text = source.text
        sections = []
        for index, passage in enumerate(chunks(text, request.chunk_size)):
            points = sentences(passage)[:3] or ["（空白分隔）"]
            sections.append(
                Section(
                    index=index,
                    heading=points[0][:36],
                    text=passage,
                    key_points=points,
                    guiding_question=f"第 {index + 1} 段的主张是什么，原文提供了哪些依据？",
                )
            )
        return ReadingResult(
            source_id=request.source_id,
            summary="\n".join(s.key_points[0] for s in sections[:5]),
            sections=sections,
        )
