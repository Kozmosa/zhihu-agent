"""这里只注册路由，不写业务逻辑。"""

from fastapi import APIRouter

from zhijing.features.author.router import router as author
from zhijing.features.cards.router import router as cards
from zhijing.features.companion.router import router as companion
from zhijing.features.facts.router import router as facts
from zhijing.features.knowledge.router import router as knowledge
from zhijing.features.opinions.router import router as opinions
from zhijing.features.reader.router import router as reader
from zhijing.features.retrieval.router import router as retrieval
from zhijing.features.runs.router import router as runs
from zhijing.features.sources.router import router as sources
from zhijing.features.zhihu.companion_router import router as zhihu_companion
from zhijing.features.zhihu.question_router import router as zhihu_questions
from zhijing.features.zhihu.router import router as zhihu
from zhijing.features.zhihu.web_router import router as zhihu_web

router = APIRouter(prefix="/api/v1")
for feature_router in (
    sources,
    retrieval,
    knowledge,
    opinions,
    author,
    reader,
    cards,
    facts,
    companion,
    runs,
    zhihu,
    zhihu_questions,
    zhihu_web,
    zhihu_companion,
):
    router.include_router(feature_router)
