from __future__ import annotations

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source, SourceDraft, SourcePage
from zhijing.domain.ports import SourceRepository


class SourceService:
    def __init__(self, repository: SourceRepository):
        self.repository = repository

    def require(self, source_id: str) -> Source:
        source = self.repository.get(source_id)
        if source is None:
            raise DomainError("source_not_found", "未找到指定资料。", 404)
        return source

    def import_items(self, items: list[SourceDraft]) -> list[Source]:
        return self.repository.save_many(items)

    def list(
        self, author_id: str | None, offset: int, limit: int, question_id: str | None = None
    ) -> list[Source]:
        return self.repository.list(author_id, offset=offset, limit=limit, question_id=question_id)

    def search(
        self,
        author_id: str | None,
        query: str,
        offset: int,
        limit: int,
        question_id: str | None = None,
    ) -> SourcePage:
        return self.repository.search(author_id, query.strip(), offset, limit, question_id)

    def groups(self, by: str, query: str, offset: int, limit: int):
        return self.repository.groups(by, query.strip(), offset, limit)

    def delete(self, source_ids: list[str]):
        return self.repository.delete_many(source_ids)

    def set_question_title(self, question_id: str, title: str):
        return self.repository.set_question_title(question_id, title)
