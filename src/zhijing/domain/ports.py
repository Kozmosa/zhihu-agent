"""业务只依赖这些协议；SQLite、模型供应商均可独立替换。"""

from typing import Protocol

from zhijing.domain.models import Citation, Generation, Source, SourceDraft


class SourceRepository(Protocol):
    def save(self, draft: SourceDraft) -> Source: ...
    def get(self, source_id: str) -> Source | None: ...
    def list(self, author_id: str | None = None) -> list[Source]: ...


class Retriever(Protocol):
    def search(
        self, query: str, author_id: str | None = None, limit: int = 5
    ) -> list[Citation]: ...


class AnswerGenerator(Protocol):
    def answer(self, question: str, context: list[Citation]) -> Generation: ...
