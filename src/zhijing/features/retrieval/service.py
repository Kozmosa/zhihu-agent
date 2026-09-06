from zhijing.core.text import chunks, tokens
from zhijing.domain.citations import cite
from zhijing.domain.models import Citation
from zhijing.domain.ports import SourceRepository


class LexicalRetriever:
    """小型语料的词汇检索基线；score 是覆盖率，不是真实性置信度。"""

    def __init__(self, repository: SourceRepository):
        self.repository = repository

    def search(self, query: str, author_id: str | None = None, limit: int = 5) -> list[Citation]:
        query_tokens = tokens(query)
        if not query_tokens:
            return []
        results = []
        for source in self.repository.list(author_id):
            for index, excerpt in enumerate(chunks(source.text)):
                overlap = query_tokens & tokens(excerpt)
                score = len(overlap) / len(query_tokens)
                if score > 0:
                    results.append(cite(source, index, excerpt, score))
        return sorted(results, key=lambda item: (-item.score, item.source_id, item.chunk_index))[
            :limit
        ]
