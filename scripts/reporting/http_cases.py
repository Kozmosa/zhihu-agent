"""真实 HTTP 场景；预期值与实际响应同时进入报告。"""

import io
import time
import zipfile

from zhijing.local_auth import connect_local_client


def exercise(client, sample):
    cases = []
    connect_local_client(client)

    def check(title, method, path, expected, validate, body=None):
        started = time.perf_counter()
        response = client.request(method, path, json=body)
        try:
            actual = response.json()
            if path == "/openapi.json":
                actual = {"openapi": actual["openapi"], "paths": list(actual["paths"])}
        except ValueError:
            actual = (
                response.text[:300]
                if "text" in response.headers.get("content-type", "")
                else {
                    "bytes": len(response.content),
                    "content_type": response.headers.get("content-type"),
                }
            )
        passed = validate(response)
        cases.append(
            {
                "title": title,
                "input": f"{method} {path}",
                "expected": expected,
                "actual": {"http_status": response.status_code, "body": actual},
                "status": "通过" if passed else "失败",
                "seconds": round(time.perf_counter() - started, 4),
                "request": body,
            }
        )
        if not passed:
            raise AssertionError(f"{title}: {expected}; got {actual}")
        return response

    try:
        check(
            "服务健康检查",
            "GET",
            "/health",
            "HTTP 200 且 status=ok",
            lambda r: r.status_code == 200 and r.json()["status"] == "ok",
        )
        check(
            "交互文档入口",
            "GET",
            "/docs",
            "HTTP 200 且包含 swagger-ui",
            lambda r: r.status_code == 200 and "swagger-ui" in r.text,
        )
        check(
            "API 契约",
            "GET",
            "/openapi.json",
            "HTTP 200 且包含统一工作流接口",
            lambda r: r.status_code == 200 and "/api/v1/companion/run" in r.json()["paths"],
        )
        result = check(
            "导入示例回答",
            "POST",
            "/api/v1/sources/import",
            "HTTP 200，返回 3 条资料",
            lambda r: r.status_code == 200 and len(r.json()) == 3,
            sample,
        ).json()
        first = result[0]["id"]
        check(
            "重复导入去重",
            "POST",
            "/api/v1/sources/import",
            "返回 ID 和首次导入相同",
            lambda r: r.status_code == 200 and r.json() == result,
            sample,
        )
        check(
            "资料数量",
            "GET",
            "/api/v1/sources",
            "重复导入后仍为 3 条",
            lambda r: r.status_code == 200 and len(r.json()) == 3,
        )
        check(
            "知识地图",
            "GET",
            "/api/v1/knowledge-map",
            "7 个节点、5 条边",
            lambda r: (
                r.status_code == 200 and len(r.json()["nodes"]) == 7 and len(r.json()["edges"]) == 5
            ),
        )
        workflow = check(
            "阅读 制卡 审查 问答完整流程",
            "POST",
            "/api/v1/companion/run",
            "四个模块均有结果，主回答位于引用首位，事实证据排除自身",
            lambda r: (
                r.status_code == 200
                and all(r.json()[k] for k in ["reading", "cards", "facts", "author"])
                and r.json()["author"]["citations"][0]["source_id"] == first
                and all(
                    c["source_id"] != first for c in r.json()["facts"]["reviews"][0]["evidence"]
                )
            ),
            {
                "source_id": first,
                "tasks": ["reading", "cards", "facts", "author"],
                "question": "如何进行主动回忆？",
                "claims": ["主动回忆是尝试在不看原文的情况下回想所学内容。"],
            },
        ).json()
        payload = {"cards": workflow["cards"]["cards"]}
        check(
            "TSV 文件下载",
            "POST",
            "/api/v1/cards/export/tsv",
            "HTTP 200，包含 Tab 分隔声明和下载文件名",
            lambda r: (
                r.status_code == 200
                and "#separator:Tab" in r.text
                and ".tsv" in r.headers.get("content-disposition", "")
            ),
            payload,
        )

        def valid_apkg(response):
            if response.status_code != 200:
                return False
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                return archive.testzip() is None and "collection.anki2" in archive.namelist()

        check(
            "APKG 卡包下载",
            "POST",
            "/api/v1/cards/export/apkg",
            "HTTP 200，ZIP 完整且含 collection.anki2",
            valid_apkg,
            payload,
        )
        check(
            "不存在的资料",
            "GET",
            "/api/v1/sources/not-found",
            "HTTP 404，source_not_found",
            lambda r: r.status_code == 404 and r.json()["error"]["code"] == "source_not_found",
        )
        check(
            "跨答主主回答拒绝",
            "POST",
            "/api/v1/author/ask",
            "HTTP 422，author_mismatch",
            lambda r: r.status_code == 422 and r.json()["error"]["code"] == "author_mismatch",
            {"author_id": "demo-author-2", "question": "主动回忆", "primary_source_id": first},
        )
        check(
            "互斥输入校验",
            "POST",
            "/api/v1/reading/analyze",
            "同时提供 text/source_id 时 HTTP 422",
            lambda r: r.status_code == 422,
            {"source_id": first, "text": "重复输入"},
        )
    except Exception as error:
        if not cases or cases[-1]["status"] == "通过":
            cases.append(
                {
                    "title": "HTTP 场景异常",
                    "input": "参见 server.log",
                    "expected": "场景完成",
                    "actual": str(error),
                    "status": "失败",
                    "seconds": 0,
                }
            )
    return cases
