"""Read-only corpus membership pinned to content-addressed source IDs."""

from __future__ import annotations

from zhijing.core.errors import DomainError
from zhijing.domain.models import Source, SourceDraft, SourcePage
from zhijing.domain.ports import SourceRepository


class SourceSnapshot:
    def __init__(self, repository: SourceRepository, source_ids: list[str]):
        self.sources = {}
        for source_id in source_ids:
            source = repository.get(source_id)
            if source is None:
                raise DomainError("source_not_found", "工作流快照中的资料已不可用。", 404)
            self.sources[source_id] = source

    def get(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def list(
        self, author_id: str | None = None, *, offset: int = 0, limit: int | None = None
    ) -> list[Source]:
        selected = [
            source
            for source in self.sources.values()
            if author_id is None or source.author_id == author_id
        ]
        return selected[offset:] if limit is None else selected[offset : offset + limit]

    def search(self, author_id: str | None, query: str, offset: int, limit: int) -> SourcePage:
        query = query.casefold()
        selected = [
            source
            for source in self.list(author_id)
            if not query
            or any(
                query in text.casefold()
                for text in [source.title, source.author_name, source.text, *source.topics]
            )
        ]
        items = selected[offset : offset + limit]
        return SourcePage(
            items=items,
            total=len(selected),
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < len(selected),
        )

    def save(self, draft: SourceDraft) -> Source:
        raise DomainError("snapshot_read_only", "工作流资料快照不可修改。", 409)

    def save_many(self, drafts: list[SourceDraft]) -> list[Source]:
        raise DomainError("snapshot_read_only", "工作流资料快照不可修改。", 409)
