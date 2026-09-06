from zhijing.core.errors import DomainError
from zhijing.core.text import sentences
from zhijing.domain.ports import SourceRepository
from zhijing.features.cards.schemas import Card, CardRequest, CardSet


class CardService:
    def __init__(self, repository: SourceRepository):
        self.repository = repository

    def generate(self, request: CardRequest) -> CardSet:
        source = self.repository.get(request.source_id)
        if source is None:
            raise DomainError("source_not_found", "制卡资料不存在。", 404)
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
