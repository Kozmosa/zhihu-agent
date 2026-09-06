"""默认只摘录证据，绝不把离线模板包装成大模型生成。"""

from zhijing.domain.models import Citation, Generation


class ExtractiveGenerator:
    def answer(self, question: str, context: list[Citation]) -> Generation:
        excerpts = [f"[{i}] {item.excerpt}" for i, item in enumerate(context, 1)]
        return Generation(
            text="以下为相关历史回答摘录，请结合原文判断：\n" + "\n".join(excerpts),
            mode="extractive",
        )
