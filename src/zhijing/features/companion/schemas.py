from typing import Annotated, Literal

from pydantic import Field

from zhijing.domain.models import NonBlank, Schema, ShortText
from zhijing.features.author.schemas import AuthorAnswer
from zhijing.features.cards.schemas import CardSet
from zhijing.features.facts.schemas import FactResult
from zhijing.features.knowledge.schemas import KnowledgeGraph
from zhijing.features.reader.schemas import ReadingResult

Task = Literal["reading", "cards", "facts", "author", "knowledge"]
TASK_ORDER: tuple[Task, ...] = ("reading", "cards", "facts", "author", "knowledge")


class CompanionRequest(Schema):
    source_id: ShortText
    tasks: list[Task] = Field(
        default_factory=lambda: ["reading", "cards"], min_length=1, max_length=5
    )
    question: Annotated[NonBlank, Field(max_length=2000)] | None = None
    claims: list[Annotated[NonBlank, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=20
    )
    knowledge_scope: Literal["author", "library"] = "author"
    knowledge_limit: int = Field(100, ge=1, le=500)


class CompanionResult(Schema):
    source_id: str
    reading: ReadingResult | None = None
    cards: CardSet | None = None
    facts: FactResult | None = None
    author: AuthorAnswer | None = None
    knowledge: KnowledgeGraph | None = None
