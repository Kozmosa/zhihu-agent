"""业务只依赖这些协议；SQLite、模型供应商均可独立替换。"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from zhijing.domain.models import (
    Citation,
    Generation,
    Source,
    SourceDraft,
    SourceGroupPage,
    SourcePage,
)


class SourceRepository(Protocol):
    def save(self, draft: SourceDraft) -> Source: ...
    def save_many(self, drafts: list[SourceDraft]) -> list[Source]: ...
    def get(self, source_id: str) -> Source | None: ...
    def list(
        self,
        author_id: str | None = None,
        *,
        offset: int = 0,
        limit: int | None = None,
        question_id: str | None = None,
    ) -> list[Source]: ...
    def search(
        self,
        author_id: str | None,
        query: str,
        offset: int,
        limit: int,
        question_id: str | None = None,
    ) -> SourcePage: ...
    def groups(self, by: str, query: str, offset: int, limit: int) -> SourceGroupPage: ...
    def delete_many(self, source_ids: list[str]) -> list[str]: ...


class Retriever(Protocol):
    def search(
        self, query: str, author_id: str | None = None, limit: int = 5
    ) -> list[Citation]: ...


class AnswerGenerator(Protocol):
    def answer(self, question: str, context: list[Citation]) -> Generation: ...


ModelResult = TypeVar("ModelResult", bound=BaseModel)


class StructuredGenerator(Protocol):
    """Provider-neutral structured generation; source validation stays in each feature."""

    def generate(
        self,
        *,
        task: str,
        instructions: str,
        payload: dict,
        response_model: type[ModelResult],
    ) -> ModelResult: ...
