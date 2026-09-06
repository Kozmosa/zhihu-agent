# 知境 ZhiJing Agent：Server 首版工程指南

项目位置：`E:\CzCode\ZhiJing Agent`。首版日期：2026-09-06。

## 1. 首版定位

以“阅读一条回答 → 理解内容 → 按主题整理 → 依据历史资料追问 → 制卡 → 检查依据”为统一体验。Server 用可组合的功能服务承载流程，后续 Web 悬浮球、侧栏或独立演示页共享同一组 API。

这是一版可运行的本地工程基线。没有接入真实知乎账户、知乎数据库或联网采集，也没有把示例内容标成真实知乎回答。默认不用模型密钥，采用透明的规则与摘录实现；可选 Ollama 仅用于答主问答生成。

| 功能 | 首版实现 | 边界 |
| --- | --- | --- |
| 资料库 | JSON 导入、SQLite 持久化、答主过滤、分页、来源保留、重复导入去重 | 不抓取 URL；单条事务，批次中存储失败可能已提交前面的记录 |
| 知识地图 | 按 topics 生成 nodes / edges / position，可供 XYFlow 前端消费 | 标签由导入者提供，不自动推断知识关系；初始布局简单 |
| 答主.skill | 同答主检索、指定主回答、引用片段、无依据时说明不足 | 默认历史摘录；不是原答主本人；Ollama 内容仍需核对 |
| 长文拆解 | 有界分段、原文保留、要点摘录、导读问题 | 首句摘录与模板问题，尚未实现语义论证分析 |
| 记忆卡片 | 原文回忆草稿、TSV、真实 `.apkg` 卡包 | 可编辑卡片后导出；尚未对接 AnkiConnect；需审阅卡片质量 |
| 事实审查 | 明确主张逐条检索、相同表述/相关证据/依据不足、排除指定来源 | 无自动真假裁决；无联网证据验证；精确匹配限定在单一片段内 |
| 统一入口 | 一次请求组合阅读、制卡、审查、问答 | 显式工作流，无自动工具规划；任一任务失败返回错误 |

## 2. 立即启动

已创建独立 Python 3.12.7 虚拟环境：`E:\CzCode\codex\envs\zhijing`，没有向系统 Python 或 Conda base 安装这些依赖。

在 PowerShell 执行：

```powershell
& 'E:\CzCode\codex\launchers\start-zhijing.ps1'
```

默认监听 `127.0.0.1:8000`。访问 `http://127.0.0.1:8000/docs` 使用交互式 API 文档；`/openapi.json` 是机器可读契约，`/health` 是进程就绪检查。Swagger UI 的脚本来自 CDN，离线时可直接使用 Python 演示或 OpenAPI JSON。

在另一个终端运行完整演示：

```powershell
Set-Location -LiteralPath 'E:\CzCode\ZhiJing Agent'
$env:PYTHONUTF8 = '1'
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' scripts/demo.py
```

演示会导入三个明确标注 `origin=demo` 的合成回答，并调用统一入口。重复运行相同导入不会增加相同记录。修改内容会产生新的记录 ID；首版不提供删除接口。

端口冲突时：

```powershell
& 'E:\CzCode\codex\launchers\start-zhijing.ps1' -Port 8001
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

通常每个功能包含 `schemas.py`（输入输出）、`service.py`（业务）、`router.py`（HTTP）。卡片导出另拆为 `export.py`。业务服务不导入 FastAPI，不直接创建数据库连接或模型客户端。共享能力通过 `SourceRepository`、`Retriever`、`AnswerGenerator` 协议传入。

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

业务错误格式为 `{"error":{"code":"source_not_found","message":"..."}}`。输入校验错误使用 FastAPI 标准 422 `detail`。模型故障明确返回 502，不会静默伪装为成功；资料不存在返回 404，主回答与答主不匹配返回 422。

## 5. 模型与数据接入

默认 `ZHIJING_MODEL_PROVIDER=extractive`，所有功能可离线调用。需要真实生成时，先自行准备可用的 Ollama 服务与已下载模型，然后在启动服务的终端设置：

```powershell
$env:ZHIJING_MODEL_PROVIDER = 'ollama'
$env:ZHIJING_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZHIJING_OLLAMA_MODEL = '你已安装的模型名'
& 'E:\CzCode\codex\launchers\start-zhijing.ps1'
```

当前只将问题与选定引用发给模型，设置 60 秒超时和最大生成长度，不执行模型输出中的命令。切回离线模式设置 `$env:ZHIJING_MODEL_PROVIDER = 'extractive'` 后重启。健康接口报告配置的供应商，不代表模型已经在线。

知乎接入待取得实际接口、鉴权和返回格式后实现。建议在 `infrastructure` 新增提供方适配器，将获取的数据转换成 `SourceDraft` 后交给资料服务，保留答主 ID、URL 和正文。`zhihu-cli` / `zhihu-skills` 尚未调用；不要预设不存在或未获授权的公开接口。无需改动 reader、cards、knowledge 等业务模块。

目前检索是全库扫描与实时分段，适合小规模演示，未做大语料性能验证。后续可加入预分段索引、BM25 或向量数据库，实现 `Retriever` 并在容器替换。单次输入最多 10 万字符，检索与主回答只选取有限片段，不能保证覆盖完整历史观点。

## 6. Anki 导出

先调用制卡接口，将返回的 `cards` 编辑后传给导出接口。推荐 `.apkg`：包含 Front、Back、Source 三个字段，自带模板和卡组名，可在 Anki 中“导入文件”。同一来源与同一问题使用稳定 GUID，包内重复卡片去重。修改问题会成为新卡，修改答案后的更新行为取决于 Anki 导入选项。

TSV 使用 UTF-8、Tab 分隔，带字段和 HTML 头。用已有 Basic 笔记类型导入时将前两列映射到 Front/Back，第三列忽略；或创建含 Source 字段的笔记类型。TSV 的 deck_name 不控制目标卡组，需在 Anki 导入界面选择。输出转义 HTML，保留多行答案。

已经验证 `.apkg` ZIP 完整性、内部 SQLite 的 notes/cards 数量、稳定 GUID 与临时文件回收；尚未在 Anki 桌面实际点击导入。AnkiConnect 是后续可选适配器，当前不会改动用户现有卡库。

## 7. 环境重建与验证

当前依赖快照包括 FastAPI 0.141.1、Uvicorn 0.52.4、Pydantic 2.13.5、httpx 0.28.1、genanki 0.13.1。精确版本以 `requirements-lock.txt` 为准；快照不含哈希，也未验证跨平台重建。

现有环境可直接运行。如需在此机器重建一个新的独立环境，可选择新的环境目录：

```powershell
Set-Location -LiteralPath 'E:\CzCode\ZhiJing Agent'
& 'E:\anaconda\python.exe' -m venv 'E:\CzCode\codex\envs\zhijing-rebuild'
& 'E:\CzCode\codex\envs\zhijing-rebuild\Scripts\python.exe' -m pip install --cache-dir 'E:\CzCode\codex\cache\pip' -r requirements-lock.txt
# 手动使用新解释器启动，或调整启动脚本的 projectPython
& 'E:\CzCode\codex\envs\zhijing-rebuild\Scripts\python.exe' -m uvicorn zhijing.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

也可从项目目录执行 `conda env create -f environment.yml`；这个备用安装路径尚未实际执行。环境文件使用依赖范围，不等同于精确快照。

运行自动验证：

```powershell
& 'E:\CzCode\codex\launchers\test-zhijing.ps1'
```

已通过 28 项测试，覆盖持久化重启、去重、非法输入、作者隔离、主回答优先、引用原文一致、无证据回答、分段边界、图边合法性、TSV 转义、APKG 结构、审查状态、工作流以及模型错误。Ruff 检查与格式检查通过。测试依赖有两条上游弃用提示（Starlette 对 httpx 及 AnyIO 别名），目前不影响测试；升级依赖时需一并处理。

真实 HTTP 演示亦已验证：健康检查成功，知识地图返回 7 个节点与 5 条边，统一入口生成 5 张卡片、返回 2 条答主引用，API 文档页面返回 HTTP 200。该演示使用合成数据与离线模式；没有运行真实 Ollama 推理。记录保存在 `E:\CzCode\codex\qa\zhijing-http-demo.json`。

常见问题：

- 找不到 `zhijing`：从项目目录启动并带 `--app-dir src`，或使用提供的启动脚本。
- 演示连接失败：确认服务终端仍在运行，端口与 `--url` 一致。
- PowerShell 禁止执行脚本：不修改系统策略也能用上述 Python / Uvicorn 命令启动。
- 返回 422：检查 docs 中的 schema；text/source_id 二选一，输入不能仅为空白。
- 模型返回 502：确认 Ollama 地址、模型名和模型服务状态。离线摘录不依赖 Ollama。
- 中文显示异常：在终端设置 `$env:PYTHONUTF8='1'`，JSON 文件以 UTF-8 保存。

## 8. 文件位置与后续建议

源码、样例、测试与依赖描述都在项目文件夹；启动/测试脚本位于 `E:\CzCode\codex\launchers`；数据库默认位于 `E:\CzCode\codex\state\zhijing\sources.sqlite3`；自动测试临时数据在 `E:\CzCode\codex\qa`；本指南按工作区规则放在 `docx\codex`。没有删除现有用户文件。

后续优先顺序：真实知乎数据适配与来源管理 → 检索索引与质量评估 → 模型驱动的长文分析/高质量制卡 → 独立证据与人工审查机制 → 用户会话和后台任务 → Web 阅读侧栏与 XYFlow 地图。当前固定工作流便于逐步加入这些能力。

实现参考：[FastAPI 依赖注入](https://fastapi.tiangolo.com/tutorial/dependencies/)、[应用生命周期](https://fastapi.tiangolo.com/advanced/events/)、[Ollama 流式与非流式响应](https://docs.ollama.com/api/streaming)、[genanki 项目](https://github.com/kerrickstaley/genanki)、[Anki 文本导入](https://docs.ankiweb.net/importing/text-files.html)。
