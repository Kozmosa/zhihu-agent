from zhijing.core.errors import DomainError
from zhijing.core.output_policy import CARD_BACK_MAX, CARD_FRONT_MAX
from zhijing.core.text import chunks, sentences
from zhijing.domain.models import Source
from zhijing.domain.ports import SourceRepository, StructuredGenerator
from zhijing.features.cards.generation import CARDS_INSTRUCTIONS, GeneratedCards
from zhijing.features.cards.schemas import Card, CardRequest, CardSet
from zhijing.infrastructure.batching import budget_batches


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
        original_sentences = list(dict.fromkeys(sentences(source.text)))
        candidates = [s for s in original_sentences if 8 <= len(s) <= CARD_BACK_MAX]
        cards = []
        for sentence in candidates[: request.count]:
            # 留出足够长的待回忆内容，避免问题直接泄漏整句答案。
            prefix_length = min(12, len(sentence) // 3)
            prompt = "《{title}》中，“{prefix}……”的完整表述是什么？"
            prefix = sentence[:prefix_length]
            title_limit = CARD_FRONT_MAX - len(prompt.format(title="", prefix=prefix))
            title = source.title
            if len(title) > title_limit:
                title = title[: title_limit - 1] + "…"
            cards.append(
                Card(
                    front=prompt.format(title=title, prefix=prefix),
                    back=sentence,
                    source_id=source.id,
                    evidence_excerpt=sentence if sentence in source.text else None,
                )
            )
        notice = "原文摘录草稿，用于回看完整表述；请核对语境并改写为概念自测问题后复习。"
        skipped = sum(len(s) > CARD_BACK_MAX for s in original_sentences)
        if skipped:
            notice += f"已跳过 {skipped} 条超过 {CARD_BACK_MAX} 字符的完整句子，未截断原文。"
        return CardSet(cards=cards, notice=notice)

    def _generate_with_model(self, source: Source, count: int) -> CardSet:
        passages = chunks(source.text)

        def payload_for(batch: list[str]) -> dict:
            return {"title": source.title, "text": "".join(batch), "count": count}

        batches = budget_batches(
            self.generator,
            passages,
            task="cards",
            instructions=CARDS_INSTRUCTIONS,
            payload_for=payload_for,
            response_model=GeneratedCards,
        )
        generated_batches = []
        rejected = 0
        for batch in batches:
            payload = payload_for(batch)
            result = self.generator.generate(
                task="cards",
                instructions=CARDS_INSTRUCTIONS,
                payload=payload,
                response_model=GeneratedCards,
            )
            rejected += result.rejected_count
            candidates = []
            questions = set()
            for card in result.cards:
                question = " ".join(card.front.casefold().split())
                if question in questions:
                    rejected += 1
                    continue
                if card.evidence_excerpt not in payload["text"]:
                    rejected += 1
                    continue
                questions.add(question)
                candidates.append(card)
            if result.cards and not candidates:
                raise DomainError(
                    "cards_evidence_invalid",
                    "卡片证据均无法在本批原文中找到，请重试或换用其他模型。",
                    502,
                )
            generated_batches.append(candidates[:count])
        # Interleave candidates so later portions participate in a global limit.
        # Repeated questions between independent batches are expected and merged.
        cards, questions = [], set()
        for rank in range(count):
            for candidates in generated_batches:
                if rank >= len(candidates):
                    continue
                card = candidates[rank]
                question = " ".join(card.front.casefold().split())
                if question not in questions:
                    questions.add(question)
                    cards.append(Card(source_id=source.id, **card.model_dump()))
                if len(cards) == count:
                    break
            if len(cards) == count:
                break
        notice = "问题与答案由模型生成；证据摘录已核对为原文片段，但答案含义仍需人工核查。"
        if rejected:
            notice += f"已跳过 {rejected} 张格式不符、重复或证据不匹配的候选卡片。"
        if not cards:
            notice += "本次未提取到可用卡片，可换用内容更完整的资料后重试。"
        if len(batches) > 1:
            notice += (
                f"已按输入预算分 {len(batches)} 批处理全部原文；"
                f"各批候选轮流选取、全局问题去重并限量至 {count} 张。"
            )
        return CardSet(
            cards=cards,
            mode=getattr(self.generator, "mode", "ollama"),
            notice=notice,
        )
