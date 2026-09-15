"""Compare supplied/imported answers without scraping or fetching arbitrary URLs."""

import hashlib
from collections import Counter
from urllib.parse import urlsplit

from zhijing.core.errors import DomainError
from zhijing.core.text import tokens
from zhijing.domain.models import Source
from zhijing.domain.ports import SourceRepository, StructuredGenerator
from zhijing.features.knowledge.schemas import SourceExtentCounts
from zhijing.features.opinions.generation import (
    answer_reference,
    author_identity_known,
    generate_opinions,
)
from zhijing.features.opinions.schemas import (
    OpinionGroup,
    OpinionMap,
    OpinionPosition,
    OpinionRequest,
    UnclassifiedAnswer,
)
from zhijing.features.zhihu.question_models import (
    ANSWER_PATH,
    OFFICIAL_HOSTS,
    normalize_question_url,
)


def _answer_identity(source: Source) -> tuple[str, str] | None:
    url = source.provenance.canonical_url if source.provenance else source.url
    if not url:
        return None
    try:
        parsed = urlsplit(str(url))
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in OFFICIAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443 if parsed.scheme == "https" else 80}
        ):
            return None
        match = ANSWER_PATH.fullmatch(parsed.path)
        return (match[1], match[2]) if match else None
    except ValueError:
        return None


def _source_question(source: Source) -> str | None:
    identity = _answer_identity(source)
    return identity[0] if identity else None


def _question_url(question: str) -> str | None:
    if "://" in question or question.startswith(("www.", "zhihu.com", "//")):
        try:
            return normalize_question_url(question)
        except ValueError:
            raise DomainError(
                "opinion_invalid_question", "请输入问题文字或有效的知乎问题链接。", 422
            ) from None
    return None


def _is_non_answer(source: Source) -> bool:
    if source.provenance:
        return source.provenance.content_type != "answer"
    if source.url:
        return urlsplit(str(source.url)).hostname == "zhuanlan.zhihu.com"
    return False


def _known_authors(sources: list[Source]) -> int:
    return len({source.author_id for source in sources if author_identity_known(source)})


class OpinionService:
    def __init__(self, repository: SourceRepository, generator: StructuredGenerator | None = None):
        self.repository = repository
        self.generator = generator

    def _select(self, body: OpinionRequest, question_url: str | None) -> tuple[list[Source], str]:
        if body.source_ids is not None:
            sources = []
            for source_id in body.source_ids:
                source = self.repository.get(source_id)
                if source is None:
                    raise DomainError("source_not_found", "所选回答不存在，请重新选择。", 404)
                sources.append(source)
            if question_url:
                question_id = question_url.rsplit("/", 1)[1]
                if any(_source_question(source) != question_id for source in sources):
                    raise DomainError(
                        "opinion_source_question_mismatch",
                        "所选资料包含未能确认属于这个知乎问题的回答，请重新选择。",
                        422,
                    )
            return sources, "explicit_sources"
        sources = self.repository.list()
        if question_url:
            question_id = question_url.rsplit("/", 1)[1]
            return [
                source for source in sources if _source_question(source) == question_id
            ], "question_url"
        terms = tokens(body.question)

        def relevance(source: Source) -> int:
            title_matches = len(terms & tokens(source.title))
            text_matches = len(terms & tokens(source.text))
            minimum = min(2, len(terms))
            if not terms or max(title_matches, text_matches) < minimum:
                return 0
            return title_matches * 3 + text_matches

        ranked = [(relevance(source), source) for source in sources]
        ranked.sort(key=lambda item: (-item[0], item[1].id))
        return [source for score, source in ranked if score], "local_search"

    def build(self, body: OpinionRequest) -> OpinionMap:
        question_url = _question_url(body.question)
        if self.generator is None:
            raise DomainError(
                "opinion_model_required",
                "观点分类需要启用大模型。请先在后台配置模型，再生成知识地图。",
                409,
            )
        candidates, selection_mode = self._select(body, question_url)
        if not candidates:
            raise DomainError(
                "opinion_no_sources",
                "资料库中没有可用于这个问题的回答，请先导入回答或选择资料。",
                404,
            )
        selected = candidates[: body.limit]
        eligible = []
        unclassified = []
        seen_answers: dict[tuple[str, str], str] = {}
        for source in selected:
            if _is_non_answer(source):
                unclassified.append(
                    UnclassifiedAnswer(
                        **answer_reference(source, 0).model_dump(),
                        category="not_answer",
                        reason="这份资料标记为文章或其他内容，未作为回答参与观点分类。",
                    )
                )
                continue
            identity = _answer_identity(source)
            if identity in seen_answers:
                unclassified.append(
                    UnclassifiedAnswer(
                        **answer_reference(source, 0).model_dump(),
                        category="duplicate_answer_version",
                        duplicate_of_source_id=seen_answers[identity],
                        reason="同一篇知乎回答已选择其他导入版本，本轮保留最先选择的版本，不重复计入观点统计。",
                    )
                )
                continue
            if identity:
                seen_answers[identity] = source.id
            eligible.append(source)
        groups = []
        references = {}
        if eligible:
            title = (
                Counter(source.title for source in eligible).most_common(1)[0][0]
                if question_url
                else ""
            )
            generated, registry, references = generate_opinions(
                self.generator, eligible, body.question, title
            )
            by_id = {source.id: source for source in eligible}
            for group in generated.groups:
                positions = [
                    OpinionPosition(
                        **references[item.source_id].model_dump(),
                        stance=item.stance,
                        summary=item.summary,
                        evidence=[registry[key] for key in item.evidence_ids],
                    )
                    for item in group.positions
                ]
                label_hash = hashlib.sha256(group.label.encode("utf-8")).hexdigest()[:16]
                groups.append(
                    OpinionGroup(
                        id="viewpoint:" + label_hash,
                        label=group.label,
                        summary=group.summary,
                        answer_count=len(positions),
                        known_author_count=_known_authors(
                            [by_id[item.source_id] for item in positions]
                        ),
                        positions=positions,
                    )
                )
            unclassified.extend(
                UnclassifiedAnswer(
                    **references[item.source_id].model_dump(),
                    reason=item.reason,
                    category=item.category,
                )
                for item in generated.unclassified
            )
        partial = sum(reference.partial_analysis for reference in references.values())
        known = _known_authors(selected)
        classified = {item.source_id for group in groups for item in group.positions}
        notice = (
            "仅比较本次选中的已导入回答，不代表知乎全部回答或意见比例。"
            "观点及理由由模型归纳，原文引用已校验来源，语义仍需人工核对；"
            "分类针对这篇回答，不代表作者一贯立场；同一回答可能属于多个观点组。"
            "作者数按已提供的稳定标识去重，未独立核验身份，未知身份不计为不同作者。"
            "完整性标记沿用导入信息，不将摘要、节选或未知完整性的文字当作完整原文。"
        )
        if partial:
            notice += (
                f"其中 {partial} 篇仅分析了部分已导入文字；按输入预算选择开头、结尾及问题相关段落，"
                "可能遗漏其他观点和限定条件，请结合原文判断。"
            )
        if not eligible:
            notice += "所选资料均不适合作为本轮回答样本，未调用模型。"
        if any(item.category == "duplicate_answer_version" for item in unclassified):
            notice += "同一知乎回答的多个导入版本仅保留最先选择的一个进行分析，其他版本列入未分类。"
        if known < 2:
            notice += "已知作者不足两位，当前结果不能证明完成了不同作者之间的对比。"
        if selection_mode == "local_search":
            notice += "回答候选来自本地关键词匹配，未自动拉取网页，也不保证召回所有相关回答。"
        if len(candidates) > len(selected):
            notice += f"本次上限为 {body.limit} 篇，超出部分尚未分析。"
        return OpinionMap(
            question=body.question,
            question_url=question_url,
            mode=getattr(self.generator, "mode", "ollama"),
            selection_mode=selection_mode,
            groups=groups,
            unclassified=unclassified,
            total_sources=len(candidates),
            included_sources=len(selected),
            classified_sources=len(classified),
            known_author_count=known,
            unknown_author_sources=sum(not author_identity_known(source) for source in selected),
            partial_sources=partial,
            omitted_source_ids=[source.id for source in candidates[body.limit :]],
            content_extent_counts=SourceExtentCounts(
                **Counter(source.content_extent for source in selected)
            ),
            truncated=len(candidates) > len(selected),
            analysis_notice=notice,
        )
