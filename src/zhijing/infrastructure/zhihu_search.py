"""One official search request per action; no redirects, scraping or automatic retries."""

import json
import time

import httpx

from zhijing.core.config import Settings
from zhijing.core.errors import DomainError

MAX_RESPONSE_BYTES = 4_000_000


class ZhihuSearchClient:
    def __init__(self, client: httpx.Client, access_secret: str):
        self.client = client
        self._access_secret = access_secret

    def search(self, query: str, count: int) -> dict:
        if not self._access_secret:
            raise DomainError("zhihu_not_configured", "请先配置知乎 Access Secret。", 409)
        try:
            with self.client.stream(
                "GET",
                Settings.zhihu_url,
                params={"Query": query, "Count": count},
                headers={
                    "Authorization": "Bearer " + self._access_secret,
                    "X-Request-Timestamp": str(int(time.time())),
                    "Content-Type": "application/json",
                },
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise DomainError(
                            "zhihu_invalid_response",
                            "知乎搜索响应过大，请减少结果数量后重试。",
                            502,
                        )
        except httpx.TimeoutException:
            raise DomainError("zhihu_timeout", "知乎搜索超时，请稍后手动重试。", 504) from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                raise DomainError(
                    "zhihu_auth_failed", "知乎鉴权失败，请检查 Access Secret 和接口权限。", 502
                ) from None
            if status == 429:
                raise DomainError(
                    "zhihu_rate_limited", "知乎接口限流或额度不足，请检查平台用量后重试。", 429
                ) from None
            raise DomainError(
                "zhihu_unavailable", "知乎搜索服务暂时不可用，请稍后手动重试。", 502
            ) from None
        except httpx.HTTPError:
            raise DomainError(
                "zhihu_unavailable", "无法连接知乎搜索服务，请检查网络后重试。", 502
            ) from None
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise DomainError("zhihu_invalid_response", "知乎搜索返回了无效响应。", 502) from None
        if not isinstance(payload, dict) or type(payload.get("Code")) is not int:
            raise DomainError("zhihu_invalid_response", "知乎搜索响应缺少有效状态码。", 502)
        code = payload["Code"]
        if code != 0:
            if code == 20001:
                raise DomainError(
                    "zhihu_auth_failed", "知乎鉴权失败，请检查 Access Secret 和接口权限。", 502
                )
            if code == 30001:
                raise DomainError(
                    "zhihu_rate_limited", "知乎接口限流或额度不足，请检查平台用量后重试。", 429
                )
            if code == 10001:
                raise DomainError(
                    "zhihu_query_rejected", "知乎接口未接受搜索参数，请修改关键词。", 502
                )
            raise DomainError("zhihu_unavailable", "知乎搜索未成功，请稍后手动重试。", 502)
        data = payload.get("Data")
        if not isinstance(data, dict) or not isinstance(data.get("Items"), list):
            raise DomainError("zhihu_invalid_response", "知乎搜索响应缺少结果列表。", 502)
        return data

    def contains_secret(self, item: dict) -> bool:
        # Do not expose a credential if a malformed upstream response happens to reflect it.
        return bool(
            self._access_secret and self._access_secret in json.dumps(item, ensure_ascii=False)
        )
