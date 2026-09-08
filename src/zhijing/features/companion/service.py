"""Deterministic five-capability orchestration with explicit evidence scope."""

from collections.abc import Callable

from pydantic import BaseModel

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source
from zhijing.domain.ports import SourceRepository
from zhijing.features.author.schemas import AuthorQuestion
from zhijing.features.author.service import AuthorService
from zhijing.features.cards.schemas import CardRequest
from zhijing.features.cards.service import CardService
from zhijing.features.companion.schemas import (
    TASK_ORDER,
    CompanionRequest,
    CompanionResult,
    Task,
)
from zhijing.features.facts.schemas import FactRequest
from zhijing.features.facts.service import FactService
from zhijing.features.knowledge.service import KnowledgeService
from zhijing.features.reader.schemas import ReadingRequest
from zhijing.features.reader.service import ReaderService
from zhijing.features.retrieval.service import LexicalRetriever
from zhijing.features.sources.service import SourceService


class _ControlledGenerator:
    """Check cooperative controls around every upstream call, including batches."""

    def __init__(self, generator, checkpoint: Callable[[], None]):
        self.generator = generator
        self.checkpoint = checkpoint

    def __getattr__(self, name):
        return getattr(self.generator, name)

    def generate(self, **kwargs):
        self.checkpoint()
        result = self.generator.generate(**kwargs)
        self.checkpoint()
        return result

    def answer(self, question, context):
        self.checkpoint()
        result = self.generator.answer(question, context)
        self.checkpoint()
        return result


class CompanionService:
    def __init__(
        self,
        sources: SourceService,
        reader: ReaderService,
        cards: CardService,
        facts: FactService,
        author: AuthorService,
        knowledge: KnowledgeService | None = None,
    ):
        self.sources, self.reader, self.cards = sources, reader, cards
        self.facts, self.author = facts, author
        self.knowledge = knowledge

    def validate(self, request: CompanionRequest) -> Source:
        source = self.sources.require(request.source_id)
        if "author" in request.tasks and not request.question:
            raise DomainError("question_required", "答主问答任务需要 question。", 422)
        if "facts" in request.tasks and not request.claims:
            raise DomainError("claims_required", "事实审查任务需要显式提供 claims。", 422)
        if "knowledge" in request.tasks and self.knowledge is None:
            raise DomainError("knowledge_unavailable", "知识地图尚未装配。", 503)
        return source

    def for_repository(
        self, repository: SourceRepository, checkpoint: Callable[[], None] | None = None
    ) -> "CompanionService":
        """Keep this request's model clients while freezing its corpus membership."""
        retriever = LexicalRetriever(repository)

        def controlled(generator):
            if generator is not None and checkpoint is not None:
                return _ControlledGenerator(generator, checkpoint)
            return generator

        return CompanionService(
            SourceService(repository),
            ReaderService(repository, generator=controlled(self.reader.generator)),
            CardService(repository, generator=controlled(self.cards.generator)),
            FactService(repository, retriever, generator=controlled(self.facts.generator)),
            AuthorService(repository, retriever, controlled(self.author.generator)),
            KnowledgeService(repository, generator=controlled(self.knowledge.generator))
            if self.knowledge is not None
            else None,
        )

    def execute(self, request: CompanionRequest, task: Task) -> BaseModel:
        source = self.sources.require(request.source_id)
        if task == "reading":
            return self.reader.analyze(ReadingRequest(source_id=source.id))
        if task == "cards":
            return self.cards.generate(CardRequest(source_id=source.id))
        if task == "facts":
            return self.facts.review(
                FactRequest(claims=request.claims, exclude_source_ids=[source.id])
            )
        if task == "author":
            return self.author.ask(
                AuthorQuestion(
                    author_id=source.author_id,
                    question=request.question,
                    primary_source_id=source.id,
                )
            )
        if task == "knowledge" and self.knowledge is not None:
            author_id = source.author_id if request.knowledge_scope == "author" else None
            return self.knowledge.build(author_id, request.knowledge_limit)
        raise DomainError("task_unavailable", "所选任务未装配。", 503)

    def run(self, request: CompanionRequest) -> CompanionResult:
        source = self.validate(request)
        result = CompanionResult(source_id=source.id)
        for task in TASK_ORDER:
            if task in request.tasks:
                setattr(result, task, self.execute(request, task))
        return result
