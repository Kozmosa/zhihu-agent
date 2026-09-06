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
from zhijing.features.sources.service import SourceService
from zhijing.infrastructure.generation import ExtractiveGenerator
from zhijing.infrastructure.ollama import OllamaGenerator
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
    export_dir: Path
    model_client: httpx.Client | None = None

    def close(self) -> None:
        if self.model_client:
            self.model_client.close()


def build_container(settings: Settings) -> Container:
    if settings.model_provider not in {"extractive", "ollama"}:
        raise ValueError("ZHIJING_MODEL_PROVIDER must be extractive or ollama")
    repository = SQLiteSourceRepository(settings.data_dir / "sources.sqlite3")
    repository.initialize()
    client = None
    generator = ExtractiveGenerator()
    if settings.model_provider == "ollama":
        client = httpx.Client(base_url=settings.ollama_url, timeout=60, trust_env=False)
        generator = OllamaGenerator(client, settings.ollama_model)
    sources = SourceService(repository)
    retriever = LexicalRetriever(repository)
    author = AuthorService(repository, retriever, generator)
    reader, cards = ReaderService(repository), CardService(repository)
    facts = FactService(repository, retriever)
    return Container(
        sources=sources,
        retriever=retriever,
        author=author,
        reader=reader,
        cards=cards,
        facts=facts,
        knowledge=KnowledgeService(repository),
        companion=CompanionService(sources, reader, cards, facts, author),
        export_dir=settings.data_dir / "exports-tmp",
        model_client=client,
    )
