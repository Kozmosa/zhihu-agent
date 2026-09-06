from zhijing.core.errors import DomainError
from zhijing.domain.models import Source, SourceDraft
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
        return [self.repository.save(item) for item in items]

    def list(self, author_id: str | None, offset: int, limit: int) -> list[Source]:
        return self.repository.list(author_id)[offset : offset + limit]
