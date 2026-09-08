"""唯一依赖装配处，新增实现不需要修改业务模块。"""

from dataclasses import dataclass
from pathlib import Path

import httpx

from zhijing.core.config import Settings
from zhijing.features.author.service import AuthorService
from zhijing.features.cards.service import CardService
from zhijing.features.companion.service import CompanionService
from zhijing.features.facts.service import FactService
from zhijing.features.knowledge.service import KnowledgeService
from zhijing.features.reader.service import ReaderService
from zhijing.features.retrieval.service import LexicalRetriever
from zhijing.features.runs.service import RunService
from zhijing.features.sources.service import SourceService
from zhijing.infrastructure.generation import ExtractiveGenerator
from zhijing.infrastructure.ollama import OllamaGenerator
from zhijing.infrastructure.openai_compatible import OpenAICompatibleGenerator
from zhijing.infrastructure.sqlite_runs import SQLiteRunRepository
from zhijing.infrastructure.sqlite_sources import SQLiteSourceRepository


@dataclass
class Container:
    sources: SourceService
    retriever: LexicalRetriever
    author: AuthorService
    reader: ReaderService
    cards: CardService
    facts: FactService
    knowledge: KnowledgeService
    companion: CompanionService
    runs: RunService
    export_dir: Path
    model_client: httpx.Client | None = None

    def close(self) -> None:
        if self.model_client:
            self.model_client.close()


def build_container(settings: Settings) -> Container:
    if errors := settings.validation_errors():
        raise ValueError(" ".join(errors))
    repository = SQLiteSourceRepository(settings.data_dir / "sources.sqlite3")
    repository.initialize()
    run_repository = SQLiteRunRepository(settings.data_dir / "runs.sqlite3")
    run_repository.initialize()
    client = None
    generator = ExtractiveGenerator()
    structured = None
    if settings.model_provider == "ollama":
        headers = (
            {"Authorization": f"Bearer {settings.ollama_api_key}"}
            if settings.ollama_api_key
            else {}
        )
        client = httpx.Client(
            base_url=settings.ollama_url,
            timeout=settings.ollama_timeout,
            headers=headers,
            trust_env=False,
        )
        structured = OllamaGenerator(
            client,
            settings.ollama_model,
            output_format=settings.ollama_format,
            max_input_chars=settings.ollama_max_input_chars,
            num_predict=settings.ollama_num_predict,
            num_ctx=settings.ollama_num_ctx,
        )
        generator = structured
    elif settings.model_provider == "openai":
        client = httpx.Client(
            base_url=settings.openai_url,
            timeout=settings.openai_timeout,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"}
            if settings.openai_api_key
            else {},
            trust_env=False,
        )
        structured = OpenAICompatibleGenerator(
            client,
            settings.openai_model,
            output_format=settings.openai_format,
            max_input_chars=settings.openai_max_input_chars,
            num_predict=settings.openai_max_tokens,
            num_ctx=settings.openai_context_window,
            thinking=settings.openai_thinking,
        )
        generator = structured
    sources = SourceService(repository)
    retriever = LexicalRetriever(repository)
    author = AuthorService(repository, retriever, generator)
    reader, cards = (
        ReaderService(repository, generator=structured),
        CardService(repository, generator=structured),
    )
    facts = FactService(repository, retriever, generator=structured)
    knowledge = KnowledgeService(repository, generator=structured)
    companion = CompanionService(sources, reader, cards, facts, author, knowledge)
    runs = RunService(
        run_repository,
        companion,
        provider=settings.model_provider,
        model=getattr(settings, f"{settings.model_provider}_model", None),
    )
    return Container(
        sources=sources,
        retriever=retriever,
        author=author,
        reader=reader,
        cards=cards,
        facts=facts,
        knowledge=knowledge,
        companion=companion,
        runs=runs,
        export_dir=settings.data_dir / "exports-tmp",
        model_client=client,
    )
