from zhijing.core.errors import DomainError
from zhijing.core.text import chunks, tokens
from zhijing.domain.citations import cite
from zhijing.domain.ports import AnswerGenerator, Retriever, SourceRepository
from zhijing.features.author.schemas import AuthorAnswer, AuthorQuestion


class AuthorService:
    def __init__(
        self, repository: SourceRepository, retriever: Retriever, generator: AnswerGenerator
    ):
        self.repository = repository
        self.retriever = retriever
        self.generator = generator

    def ask(self, request: AuthorQuestion) -> AuthorAnswer:
        context = self.retriever.search(request.question, request.author_id, request.top_k)
        if request.primary_source_id:
            source = self.repository.get(request.primary_source_id)
            if source is None:
                raise DomainError("source_not_found", "主回答不存在。", 404)
            if source.author_id != request.author_id:
                raise DomainError("author_mismatch", "主回答不属于指定答主。", 422)
            passages = chunks(source.text)
            query = tokens(request.question)
            # 主回答即使检索未命中也显式纳入，保留 chunk_index 以便定位。
            index = max(range(len(passages)), key=lambda i: len(query & tokens(passages[i])))
            score = len(query & tokens(passages[index])) / len(query) if query else 0
            primary = cite(source, index, passages[index], score)
            context = [primary] + [c for c in context if c.source_id != source.id]
            context = context[: request.top_k]
        if not context:
            return AuthorAnswer(
                answer="现有资料没有找到相关内容，无法依据该答主历史回答作答。",
                mode="extractive",
                citations=[],
            )
        generated = self.generator.answer(request.question, context)
        return AuthorAnswer(answer=generated.text, mode=generated.mode, citations=context)
