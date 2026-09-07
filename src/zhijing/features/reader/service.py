from zhijing.core.errors import DomainError
from zhijing.core.text import chunks, sentences
from zhijing.domain.ports import SourceRepository, StructuredGenerator
from zhijing.features.reader.generation import READING_INSTRUCTIONS, GeneratedReading
from zhijing.features.reader.schemas import ReadingRequest, ReadingResult, Section


class ReaderService:
    def __init__(self, repository: SourceRepository, generator: StructuredGenerator | None = None):
        self.repository = repository
        self.generator = generator

    def analyze(self, request: ReadingRequest) -> ReadingResult:
        text = request.text
        if request.source_id:
            source = self.repository.get(request.source_id)
            if source is None:
                raise DomainError("source_not_found", "待拆解资料不存在。", 404)
            text = source.text
        passages = chunks(text, request.chunk_size)
        if self.generator is not None:
            return self._analyze_with_model(request.source_id, passages)
        sections = []
        for index, passage in enumerate(passages):
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

    def _analyze_with_model(self, source_id: str | None, passages: list[str]) -> ReadingResult:
        result = self.generator.generate(
            task="reading",
            instructions=READING_INSTRUCTIONS,
            payload={
                "sections": [{"index": index, "text": text} for index, text in enumerate(passages)]
            },
            response_model=GeneratedReading,
        )
        indices = [section.index for section in result.sections]
        if sorted(indices) != list(range(len(passages))):
            raise DomainError(
                "model_invalid_response", "阅读模型遗漏、重复或虚构了原文段落索引。", 502
            )
        by_index = {section.index: section for section in result.sections}
        return ReadingResult(
            source_id=source_id,
            mode=getattr(self.generator, "mode", "ollama"),
            summary=result.summary,
            sections=[
                Section(text=text, **by_index[index].model_dump())
                for index, text in enumerate(passages)
            ],
            notice="摘要、标题、要点与导读问题由模型生成，需结合原文核对；各段原文保持不变。",
        )
