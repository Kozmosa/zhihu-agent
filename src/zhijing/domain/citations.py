from zhijing.domain.models import Citation, Source


def cite(source: Source, index: int, excerpt: str, score: float) -> Citation:
    return Citation(
        source_id=source.id,
        title=source.title,
        author_id=source.author_id,
        url=str(source.url) if source.url else None,
        chunk_index=index,
        excerpt=excerpt,
        score=round(score, 4),
    )
