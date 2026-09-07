# 知境 ZhiJing Agent：Server v0.2 工程指南

项目位置：`E:\CzCode\ZhiJing Agent`。更新日期：2026-09-07。

## 1. 当前定位

以“阅读一条回答 → 理解内容 → 按主题整理 → 依据历史资料追问 → 制卡 → 检查依据”为统一体验。Server 用可组合的功能服务承载流程，后续 Web 悬浮球、侧栏或独立演示页共享同一组 API。

这是一版可运行的本地工程基线。没有接入真实知乎账户、知乎数据库或联网采集，示例为明确标记的合成资料。默认不用模型密钥，采用规则与摘录实现；v0.2 已为以下五项知识能力实现 Ollama 适配，可使用统一配置连接已有模型服务。

| 功能 | 当前实现 | 边界 |
| --- | --- | --- |
| 资料库 | JSON 导入、SQLite 持久化、答主过滤、分页、来源保留、重复导入去重 | 不抓取 URL；单条事务，批次中存储失败可能已提交前面的记录 |
| 知识地图 | 离线按 topics 归类；模型提取概念及支持、反驳、相关、前置、限定、补充关系，返回 XYFlow 数据 | 节点与关系回填真实证据；语义仍需核对，布局简单 |
| 答主.skill | 同答主检索、指定主回答；离线摘录或模型带编号回答 | 不是原答主本人；引用列表是完整检索上下文，未必逐条用于答案 |
| 长文拆解 | 服务端分段并保留原文；模型生成摘要、段标题、要点和导读问题 | 模型不能改写原文字段；输出必须覆盖每个段落索引恰好一次 |
| 记忆卡片 | 离线回忆模板或模型概念问答；真实原文摘录；TSV、`.apkg` 导出 | 证据摘录存在不保证答案含义正确；导出保留摘录，尚未对接 AnkiConnect |
| 事实审查 | 离线匹配；模型判断支持、反驳、混合或不足，保留适用条件，排除指定来源 | 只审查导入资料与主张的关系，不证明客观真假，不进行联网查证 |
| 统一入口 | 一次请求组合阅读、制卡、审查、问答 | 显式工作流，无自动工具规划；任一任务失败返回错误 |

## 2. 立即启动

已创建独立 Python 3.12.7 虚拟环境：`E:\CzCode\codex\envs\zhijing`，没有向系统 Python 或 Conda base 安装这些依赖。

在 PowerShell 执行：

```powershell
& 'E:\CzCode\ZhiJing Agent\Start.cmd'
```

`Start.cmd` 与 `main.py` 均可从任意工作目录调用。默认监听 `127.0.0.1:8000`。访问 `http://127.0.0.1:8000/docs` 使用交互式 API 文档；`/openapi.json` 是机器可读契约，`/health` 是进程就绪检查，不证明模型可用。Swagger UI 的脚本来自 CDN，离线时可直接使用 Python 演示或 OpenAPI JSON。

在另一个终端运行完整演示：

```powershell
Set-Location -LiteralPath 'E:\CzCode\ZhiJing Agent'
$env:PYTHONUTF8 = '1'
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' scripts/demo.py
```

首次使用可直接把 `examples/sources.json` 作为请求体提交到 `POST /api/v1/sources/import`；启动服务不会自动导入资料。演示脚本会读取该文件、导入明确标注 `origin=demo` 的合成回答并调用统一入口。重复导入相同资料不会增加记录；修改内容会产生新的 ID，目前不提供删除接口。

端口冲突时：

```powershell
& 'E:\CzCode\ZhiJing Agent\Start.cmd' --port 8001
# 另一个终端
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\demo.py' --url http://127.0.0.1:8001
```

在服务终端按 Ctrl+C 停止。服务默认是单机开发用途，尚无登录、用户隔离、限流或公网部署配置。不要把默认监听地址改成公网地址直接上线。

## 3. 文件分区与依赖方向

```text
ZhiJing Agent/
├── pyproject.toml              包、依赖、测试与代码规范配置
├── requirements-lock.txt       本次验证环境的精确依赖版本
├── environment.yml            可选 Conda Python 3.12 环境描述
├── .env.example               环境变量参考，不自动加载
├── project-info.json          指南与启动入口索引
├── examples/sources.json       合成示例数据
├── scripts/demo.py            HTTP 完整流程演示
├── scripts/ollama_smoke.py     五项模型接口验证，支持 mock / live
├── tests/                     按功能划分的测试
└── src/zhijing/
    ├── app.py                 应用工厂、生命周期、错误映射
    ├── api.py                 路由注册
    ├── dependencies.py        HTTP 请求取得已装配服务
    ├── container.py           依赖装配；替换实现只改这里
    ├── core/                  配置、业务错误、通用文本工具
    ├── domain/                共享资料/引用模型和接口协议
    ├── infrastructure/        SQLite、离线摘录、Ollama 适配器
    └── features/
        ├── sources/           资料导入与查询
        ├── retrieval/         中文双字/英文词检索
        ├── knowledge/         知识地图
        ├── author/            答主问答
        ├── reader/            长文拆解
        ├── cards/             卡片生成与导出
        ├── facts/             证据审查
        └── companion/         显式流程编排
```

通常每个功能包含 `schemas.py`（输入输出）、`service.py`（业务）、`router.py`（HTTP）；模型提示与输出结构放入 `generation.py` 或 `model_schemas.py`，卡片导出另拆为 `export.py`。业务服务不导入 FastAPI，不直接创建数据库连接或模型客户端。共享能力通过 `SourceRepository`、`Retriever`、`AnswerGenerator`、`StructuredGenerator` 协议传入。

依赖方向：HTTP 路由 → 功能服务 → 领域协议；基础设施实现领域协议；`container.py` 负责连接它们。`companion` 是允许调用其他功能服务的编排模块，不绕过服务访问数据库。引用构造放在 `domain/citations.py`，问答、检索和审查共享它，避免功能之间互相依赖实现细节。

新功能先定义输入输出，再写服务，最后注册路由和装配依赖。避免在 `app.py` 增加业务代码，避免在路由中拼模型提示词或 SQL。单文件接近 200 行时按职责拆分，不为减少行数压缩代码。

## 4. API 契约

除健康检查外，统一使用 `/api/v1` 前缀。

| 方法和路径 | 用途 |
| --- | --- |
| POST `/sources/import` | `{"items": [...]}` 导入 1～20 条资料 |
| GET `/sources` | `author_id`、`offset`、`limit` 查询 |
| GET `/sources/{source_id}` | 原文和来源 |
| POST `/retrieval/search` | `query`、可选 `author_id`、`limit` |
| GET `/knowledge-map` | 地图数据；可选 `author_id`、`limit` |
| POST `/author/ask` | `author_id`、`question`、可选 `primary_source_id`、`top_k` |
| POST `/reading/analyze` | `source_id` 或 `text` 二选一；可选 `chunk_size` |
| POST `/cards/generate` | `source_id`、`count` |
| POST `/cards/export/tsv` | `cards`、可选 `deck_name`；下载 TSV |
| POST `/cards/export/apkg` | `cards`、可选 `deck_name`；下载卡包 |
| POST `/facts/review` | `claims`、可选 `author_id`、`exclude_source_ids` |
| POST `/companion/run` | 按来源组合各功能 |

导入字段与完整示例见项目的 `examples/sources.json`。`url` 只允许 HTTP(S)，仅作为来源元数据保留；Server 不请求用户提交的 URL。`origin` 是导入者声明的来源类型，不表示平台认证。

统一入口示例（将 source_id 换成导入响应的 ID）：

```json
{
  "source_id": "导入返回的ID",
  "tasks": ["reading", "cards", "facts", "author"],
  "question": "如何进行主动回忆？",
  "claims": ["主动回忆是尝试在不看原文的情况下回想所学内容。"]
}
```

`author` 任务要求 question；`facts` 要求显式 claims，且自动排除当前原文作为证据。未选择的功能返回 null。知识地图单独请求，避免每次阅读重复返回整张图。

业务错误格式为 `{"error":{"code":"source_not_found","message":"..."}}`。输入校验错误使用 FastAPI 标准 422 `detail`。模型故障或非法输出返回 502，输入预算超限返回 413，均不静默截断或退回规则；资料不存在返回 404，主回答与答主不匹配返回 422。

## 5. 模型与数据接入

默认 `ZHIJING_MODEL_PROVIDER=extractive`，所有功能可离线调用。需要真实生成时，准备可用的 Ollama 原生 API 与模型，在启动服务的同一终端设置：

```powershell
$env:ZHIJING_MODEL_PROVIDER = 'ollama'
$env:ZHIJING_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZHIJING_OLLAMA_MODEL = '你已安装的模型名'
& 'E:\CzCode\ZhiJing Agent\Start.cmd'
```

五项服务共用 Ollama 适配器，但分别定义提示、结构化输出和业务校验。阅读发送完整分段原文，制卡发送选定原文，地图发送所选资料全部分块，问答和审查发送检索证据。默认单次调用超时 120 秒、输出预算 4096、上下文 32768；不会执行模型输出中的命令。切回离线模式设置 `$env:ZHIJING_MODEL_PROVIDER = 'extractive'` 后重启。

输入预算包括完整 system 与 prompt，其中含任务、资料和 JSON Schema；还以 UTF-8 字节数加输出预算和 512 预留估计上下文。它是保守估计，不是真实 tokenizer。超限返回 413，不静默裁剪正文。完整配置、URL 规则、可选鉴权、schema/json/prompt 模式和真实 API 验证见 [Ollama 接入说明](Ollama接入说明.md)。`.env` 不会自动加载。

五项结果通过 `mode=extractive/ollama` 标明实际路径。空地图、无证据问答与事实审查不调用模型；不存在的阅读或制卡资料直接返回 404。引用编号及摘录验证只能证明引用来自输入，不能保证模型解释、推理或事实判断正确。答主 `citations` 是输入上下文列表，答案中的 `[n]` 对应该列表的第 n 条；完整列表不表示模型逐条使用了所有证据。

知乎接入待取得实际接口、鉴权和返回格式后实现。建议在 `infrastructure` 新增提供方适配器，将获取的数据转换成 `SourceDraft` 后交给资料服务，保留答主 ID、URL 和正文。`zhihu-cli` / `zhihu-skills` 尚未调用；不要预设不存在或未获授权的公开接口。无需改动 reader、cards、knowledge 等业务模块。

目前检索是全库扫描与实时分段，适合小规模演示，未做大语料性能验证。后续可加入预分段索引、BM25 或向量数据库，实现 `Retriever` 并在容器替换。单篇正文上限 10 万字符，但模型输入还有独立预算，因此允许导入不代表可一次完整推理。检索与主回答只选取有限片段，不能保证覆盖完整历史观点；地图的资料 limit 与 truncated 明确报告范围。

## 6. Anki 导出

先调用制卡接口，将返回的 `cards` 编辑后传给导出接口。`.apkg` 包含 Front、Back、Source 三个字段，自带模板和卡组名；模型卡片的原文摘录随来源信息保留，TSV 同样保留。可在 Anki 中“导入文件”。同一来源与同一问题使用稳定 GUID，包内重复卡片去重。修改问题会成为新卡，修改答案后的更新行为取决于 Anki 导入选项。

TSV 使用 UTF-8、Tab 分隔，带字段和 HTML 头。用已有 Basic 笔记类型导入时将前两列映射到 Front/Back，第三列忽略；或创建含 Source 字段的笔记类型。TSV 的 deck_name 不控制目标卡组，需在 Anki 导入界面选择。输出转义 HTML，保留多行答案。

已经验证 `.apkg` ZIP 完整性、内部 SQLite 的 notes/cards 数量、稳定 GUID 与临时文件回收；尚未在 Anki 桌面实际点击导入。AnkiConnect 是后续可选适配器，当前不会改动用户现有卡库。

## 7. 环境重建与验证

当前依赖快照包括 FastAPI 0.141.1、Uvicorn 0.52.4、Pydantic 2.13.5、httpx 0.28.1、genanki 0.13.1。精确版本以 `requirements-lock.txt` 为准；快照不含哈希，也未验证跨平台重建。

现有环境可直接运行。如需在此机器重建一个新的独立环境，可选择新的环境目录：

```powershell
Set-Location -LiteralPath 'E:\CzCode\ZhiJing Agent'
& 'E:\anaconda\python.exe' -m venv 'E:\CzCode\codex\envs\zhijing-rebuild'
& 'E:\CzCode\codex\envs\zhijing-rebuild\Scripts\python.exe' -m pip install --cache-dir 'E:\CzCode\codex\cache\pip' -r requirements-lock.txt
# 使用新解释器调用正式入口
& 'E:\CzCode\codex\envs\zhijing-rebuild\Scripts\python.exe' main.py
```

也可从项目目录执行 `conda env create -f environment.yml`；这个备用安装路径尚未实际执行。环境文件使用依赖范围，不等同于精确快照。

运行自动验证：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\run_report.py'
```

最新测试数量、结果、版本与原始响应见根目录 [运行测试报告](运行测试报告.md)。覆盖离线兼容、五项模型接线、原文保持、输入输出校验、引用及图结构、卡包导出、异常响应和正式入口 HTTP 流程。

固定模型响应的 `--mock` 验证接线与契约，不能证明真实 LLM 的理解和生成质量。已有模型 API 后运行 `scripts/ollama_smoke.py --live`；它会通过正式入口启动独立服务，测试五项能力，结束后关闭本次测试进程，具体命令见接入说明。真实模型成功仍需人工检查卡片、摘要、关系和事实分析的内容。

常见问题：

- 找不到 `zhijing`：使用项目 `Start.cmd` 或 `main.py` 正式入口。
- 演示连接失败：确认服务终端仍在运行，端口与 `--url` 一致。
- PowerShell 禁止执行脚本：不修改系统策略也能用上述 Python / Uvicorn 命令启动。
- 返回 422：检查 docs 中的 schema；text/source_id 二选一，输入不能仅为空白。
- 模型返回 502：检查错误码、地址、模型名、鉴权、输出格式和长度。模型输入超限为 413。
- 中文显示异常：在终端设置 `$env:PYTHONUTF8='1'`，JSON 文件以 UTF-8 保存。

## 8. 文件位置与后续建议

源码、样例、测试、正式入口和本指南都在项目文件夹；旧的工作区启动辅助脚本仍保留。数据库默认位于 `E:\CzCode\codex\state\zhijing\sources.sqlite3`，自动测试临时数据在 `E:\CzCode\codex\qa`，报告原始证据位于项目 `reports`。

后续重点是接入真实授权资料、改进检索与模型质量评估、增加人工证据审查、用户会话与后台任务，再扩展 Web 阅读侧栏和 XYFlow 地图。当前 companion 仍为显式顺序工作流，没有模型自主工具规划。

实现参考：[FastAPI 依赖注入](https://fastapi.tiangolo.com/tutorial/dependencies/)、[应用生命周期](https://fastapi.tiangolo.com/advanced/events/)、[Ollama 流式与非流式响应](https://docs.ollama.com/api/streaming)、[genanki 项目](https://github.com/kerrickstaley/genanki)、[Anki 文本导入](https://docs.ankiweb.net/importing/text-files.html)。
