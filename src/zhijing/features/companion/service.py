"""确定性工作流编排；模块调用可追踪，不让模型任意执行工具或命令。"""

from zhijing.core.errors import DomainError
from zhijing.features.author.schemas import AuthorQuestion
from zhijing.features.author.service import AuthorService
from zhijing.features.cards.schemas import CardRequest
from zhijing.features.cards.service import CardService
from zhijing.features.companion.schemas import CompanionRequest, CompanionResult
from zhijing.features.facts.schemas import FactRequest
from zhijing.features.facts.service import FactService
from zhijing.features.reader.schemas import ReadingRequest
from zhijing.features.reader.service import ReaderService
from zhijing.features.sources.service import SourceService


class CompanionService:
    def __init__(
        self,
        sources: SourceService,
        reader: ReaderService,
        cards: CardService,
        facts: FactService,
        author: AuthorService,
    ):
        self.sources, self.reader, self.cards = sources, reader, cards
        self.facts, self.author = facts, author

    def run(self, request: CompanionRequest) -> CompanionResult:
        source = self.sources.require(request.source_id)
        tasks = set(request.tasks)
        if "author" in tasks and not request.question:
            raise DomainError("question_required", "答主问答任务需要 question。", 422)
        if "facts" in tasks and not request.claims:
            raise DomainError("claims_required", "事实审查任务需要显式提供 claims。", 422)
        result = CompanionResult(source_id=source.id)
        if "reading" in tasks:
            result.reading = self.reader.analyze(ReadingRequest(source_id=source.id))
        if "cards" in tasks:
            result.cards = self.cards.generate(CardRequest(source_id=source.id))
        if "facts" in tasks:
            # 禁止用待审查的原文自身作为核查依据。
            result.facts = self.facts.review(
                FactRequest(
                    claims=request.claims,
                    exclude_source_ids=[source.id],
                )
            )
        if "author" in tasks:
            result.author = self.author.ask(
                AuthorQuestion(
                    author_id=source.author_id,
                    question=request.question,
                    primary_source_id=source.id,
                )
            )
        return result
