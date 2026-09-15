"""Derive question groups from verified Zhihu URL structure, never display titles."""

import re
from urllib.parse import urlsplit

from zhijing.domain.models import SourceDraft


def source_question_id(source: SourceDraft) -> str | None:
    value = source.provenance.canonical_url if source.provenance else source.url
    if value is None:
        return None
    try:
        url = urlsplit(str(value))
        if (
            url.scheme not in {"http", "https"}
            or url.hostname not in {"zhihu.com", "www.zhihu.com", "m.zhihu.com"}
            or url.username is not None
            or url.password is not None
            or url.port not in {None, 443 if url.scheme == "https" else 80}
        ):
            return None
        match = re.fullmatch(r"/question/([0-9]{1,30})(?:/answer/[0-9]{1,30})?/?", url.path)
        return match[1] if match else None
    except ValueError:
        return None
