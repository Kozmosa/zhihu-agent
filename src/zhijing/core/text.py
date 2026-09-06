"""可替换的轻量文本工具；当前中文检索使用字符与双字切分。"""

import re


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？.!?])\s*|\n+", text) if s.strip()]


def chunks(text: str, size: int = 600) -> list[str]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    result, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r"[。！？.!?\n]", text[start:end]))
            if boundaries:
                end = start + boundaries[-1].end()
        # 保留空白与换行，确保引用始终是原文的连续子串。
        result.append(text[start:end])
        start = end
    return result


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i : i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            words.add(run)
    return words
