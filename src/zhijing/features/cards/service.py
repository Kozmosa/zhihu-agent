from zhijing.core.errors import DomainError
from zhijing.core.text import sentences
from zhijing.domain.models import Source
from zhijing.domain.ports import SourceRepository, StructuredGenerator
from zhijing.features.cards.generation import CARDS_INSTRUCTIONS, GeneratedCards
from zhijing.features.cards.schemas import Card, CardRequest, CardSet


class CardService:
    def __init__(self, repository: SourceRepository, generator: StructuredGenerator | None = None):
        self.repository = repository
        self.generator = generator

    def generate(self, request: CardRequest) -> CardSet:
        source = self.repository.get(request.source_id)
        if source is None:
            raise DomainError("source_not_found", "制卡资料不存在。", 404)
        if self.generator is not None:
            return self._generate_with_model(source, request.count)
        candidates = list(dict.fromkeys(s for s in sentences(source.text) if 8 <= len(s) <= 1000))
        cards = []
        for sentence in candidates[: request.count]:
            # 留出足够长的待回忆内容，避免问题直接泄漏整句答案。
            prefix_length = min(12, len(sentence) // 3)
            cards.append(
                Card(
                    front=f"《{source.title}》中，“{sentence[:prefix_length]}……”的完整表述是什么？",
                    back=sentence,
                    source_id=source.id,
                )
            )
        return CardSet(cards=cards)

    def _generate_with_model(self, source: Source, count: int) -> CardSet:
        result = self.generator.generate(
            task="cards",
            instructions=CARDS_INSTRUCTIONS,
            payload={"title": source.title, "text": source.text, "count": count},
            response_model=GeneratedCards,
        )
        if len(result.cards) > count:
            raise DomainError("model_invalid_response", "模型生成的卡片数量超过请求上限。", 502)
        questions = set()
        for card in result.cards:
            question = " ".join(card.front.casefold().split())
            if question in questions:
                raise DomainError("model_invalid_response", "模型生成了重复的卡片问题。", 502)
            questions.add(question)
            if card.evidence_excerpt not in source.text:
                raise DomainError(
                    "model_invalid_response", "卡片证据摘录无法在指定资料原文中找到。", 502
                )
        return CardSet(
            cards=[Card(source_id=source.id, **card.model_dump()) for card in result.cards],
            mode=getattr(self.generator, "mode", "ollama"),
            notice="问题与答案由模型生成；证据摘录已核对为原文片段，但答案含义仍需人工核查。",
        )
