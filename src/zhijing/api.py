"""这里只注册路由，不写业务逻辑。"""

from fastapi import APIRouter

from zhijing.features.author.router import router as author
from zhijing.features.cards.router import router as cards
from zhijing.features.companion.router import router as companion
from zhijing.features.facts.router import router as facts
from zhijing.features.knowledge.router import router as knowledge
from zhijing.features.reader.router import router as reader
from zhijing.features.retrieval.router import router as retrieval
from zhijing.features.runs.router import router as runs
from zhijing.features.sources.router import router as sources
from zhijing.features.zhihu.router import router as zhihu

router = APIRouter(prefix="/api/v1")
for feature_router in (
    sources,
    retrieval,
    knowledge,
    author,
    reader,
    cards,
    facts,
    companion,
    runs,
    zhihu,
):
    router.include_router(feature_router)
