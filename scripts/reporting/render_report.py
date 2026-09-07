"""同一份实测数据输出 Markdown 和不依赖网络的 HTML 报告。"""

import html
import json
from pathlib import Path


def compact(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def table_md(rows, headers):
    def line(values):
        return (
            "| " + " | ".join(str(v).replace("|", "\\|").replace("\n", " ") for v in values) + " |"
        )

    return "\n".join([line(headers), line(["---"] * len(headers)), *[line(row) for row in rows]])


def table_html(rows, headers):
    head = "".join(f"<th>{html.escape(str(item))}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(item))}</td>" for item in row) + "</tr>"
        for row in rows
    )
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def write_reports(project, report):
    tests, http_cases = report["tests"], report["http"]
    test_pass = sum(c["status"] == "通过" for c in tests)
    http_pass = sum(c["status"] == "通过" for c in http_cases)
    overall = "通过" if report["success"] else "存在未通过项"
    intro = f"本次验证结论：{overall}。自动化案例 {test_pass}/{len(tests)} 通过，真实进程与 HTTP 案例 {http_pass}/{len(http_cases)} 通过。运行时间：{report['timestamp']}。"
    scope = "验证对象为项目正式启动入口和本地 Server。离线 HTTP 场景与五项能力 Ollama HTTP 联调均使用独立数据库和合成样例；Ollama 返回固定模拟响应，没有执行真实模型推理。"
    entry = "双击项目根目录 Start.cmd 启动服务；也可运行 python main.py --port 8000。服务默认仅监听 127.0.0.1，运行后访问 http://127.0.0.1:8000/docs；关闭服务终端或按 Ctrl+C 停止。"
    env_rows = [[key, value] for key, value in report["environment"].items()]
    checks = [
        [
            item["name"],
            "通过" if item["exit_code"] == 0 else "失败",
            f"{item['seconds']:.3f}",
            item["log"],
        ]
        for item in report["checks"]
    ]
    test_rows = [
        [
            c["id"],
            c["module"],
            c["title"],
            c["input"],
            c["expected"],
            c["status"],
            f"{c['seconds']:.3f}",
        ]
        for c in tests
    ]
    test_headers = ["编号", "模块", "案例", "输入或操作", "预期结果", "实测状态", "耗时秒"]
    http_rows = [
        [
            f"HTTP-{i:02}",
            c["title"],
            compact(c["input"]),
            c["expected"],
            c["status"],
            f"{c['seconds']:.3f}",
        ]
        for i, c in enumerate(http_cases, 1)
    ]
    http_headers = ["编号", "案例", "输入或操作", "预期结果", "实测状态", "耗时秒"]
    limitations = "未验证真实知乎接入、Anki 桌面导入、真实 Ollama 生成、并发压力、公网安全部署。HTTP 200 仅说明文档资源可返回，不代表已验证浏览器界面。当前自动化浏览器连接不可用，HTML 报告已做结构和内容检查，未做截图视觉检查。测试日志中的上游弃用警告保留在 pytest.log，未将其记作测试失败。耗时为本机单次观测，不是性能基准。"
    evidence = report["evidence"]
    replay = "在项目目录使用项目解释器运行 scripts/run_report.py，即可重新执行测试并更新本报告。每次原始证据存入 reports 下的新时间目录；测试临时数据存入 codex/qa，不覆盖业务数据库。"
    sections = [
        ("运行环境", env_rows, ["项目", "实际值"]),
        ("执行命令检查", checks, ["检查", "结果", "耗时秒", "日志"]),
        ("自动化测试案例", test_rows, test_headers),
        ("真实入口和 HTTP 测试", http_rows, http_headers),
        (
            "五项能力 Ollama HTTP 模拟联调",
            [
                [
                    case["capability"],
                    case["path"],
                    case.get("http_status", "未收到"),
                    "通过" if case["passed"] else "失败",
                    compact(case.get("checks", {})),
                ]
                for case in report.get("ollama_smoke", {}).get("cases", [])
            ],
            ["能力", "API", "HTTP状态", "结论", "实际校验"],
        ),
    ]
    md = ["# 知境运行与测试报告", intro, scope, "## 正式入口", entry]
    content = [
        f"<h1>知境运行与测试报告</h1><p class='summary'>{html.escape(intro)}</p><p>{html.escape(scope)}</p><h2>正式入口</h2><p>{html.escape(entry)}</p>"
    ]
    for title, rows, headers in sections:
        md.extend(["## " + title, table_md(rows, headers)])
        content.append(f"<h2>{title}</h2>" + table_html(rows, headers))
    md.extend(
        [
            "## 实际请求与响应",
            "场景记录见证据目录 http-results.json。以下为实际响应摘录：文本响应仅保留前 300 字符，OpenAPI 仅列版本和路径，APKG 仅记录字节数与类型。",
        ]
    )
    content.append(
        "<h2>实际请求与响应</h2><p>点击案例展开输入和响应摘录。文本响应保留前 300 字符；OpenAPI 仅列版本和路径，APKG 仅记录字节数与类型。</p>"
    )
    for case in http_cases:
        record = {"request": case.get("request"), "actual": case["actual"]}
        rendered = compact(record)
        md.extend(["### " + case["title"], "```json\n" + rendered + "\n```"])
        content.append(
            f"<details><summary>{html.escape(case['title'])} · {case['status']}</summary><pre>{html.escape(rendered)}</pre></details>"
        )
    mapping = [[c["id"], c["node"], c["actual"]] for c in tests]
    md.extend(["## 案例源码与实际断言", table_md(mapping, ["编号", "pytest 节点", "实际结果"])])
    content.append(
        "<h2>案例源码与实际断言</h2>" + table_html(mapping, ["编号", "pytest 节点", "实际结果"])
    )
    for title, text in [
        ("验证边界", limitations),
        ("复现方式", replay),
        (
            "原始证据",
            evidence
            + "，包括 JUnit XML、pytest/Ruff 日志、环境数据、HTTP 响应和源码 SHA256 清单。",
        ),
    ]:
        md.extend(["## " + title, text])
        content.append(f"<h2>{title}</h2><p>{html.escape(text)}</p>")
    css = Path(__file__).with_name("report.css").read_text("utf-8")
    (project / "运行测试报告.md").write_text("\n\n".join(md) + "\n", "utf-8")
    page = (
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>知境运行与测试报告</title><style>"
        + css
        + "</style><main>"
        + "".join(content)
        + "</main></html>"
    )
    (project / "运行测试报告.html").write_text(page, "utf-8")
