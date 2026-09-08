# ZhiJing 后端工作流与模型验收约定草案

本文件定义资料库基线之后的工作顺序、文件归属和接口提案。用户已确定本轮不制作前端，产品方向为悬浮球或桌面伴侣；五项核心能力继续沿用。除 BASELINE.md 列明的接口外，下文新增 schema 和端点都是待实现提案，需工作流开发线在共享交接文件中确认后再用于联调。

## 分工和共同编辑规则

| 开发线 | 负责范围 | 交接边界 |
| --- | --- | --- |
| 资料库命令行助手，本次执行方 | 现有 sqlite_sources、features/sources、资料库测试及其文档收尾 | B0 已完成；本轮不另起重写，不领取 companion 或前端文件 |
| 工作流开发线 | companion、runs/run_steps/artifacts、reader/cards/knowledge 分批、模型预算和 provider 通用验收脚本 | 先确认运行 schema、错误语义及模型能力配置，再实施 |
| 前端开发线 | 以后负责 web 搜索、进度、取消、历史与重试展示 | 本轮暂停前端制作；以后消费接口契约，不直接改后端 schema |
| 下一阶段共享入口编辑者 | 工作流开发线唯一编辑 `domain/models.py`、`domain/ports.py`、`container.py`、`api.py` | 本次资料库来源契约冻结后交出编辑权；任何来源接口变更先在交接文件说明 |

同一 checkout 不分别切换分支，不使用 `git add .` 或提交全部变动，不覆盖未知来源修改。提交只选明确拥有的文件；共享入口若混有多条线的修改，先逐块核对再选择性暂存。每次开始写明领取范围，结束追加测试、文件和未完成项。代码评审子代理仅是本会话内部审查，不能当作用户另一个终端或对方确认。

所有测试使用新建的隔离数据库。每轮验收应保存被测代码哈希；并发变更发生时，使用独立快照或明确缩小验收范围。评估方的 `src/_review`、未知的 `src/.backend-work` 不随应用文件无差别提交。

## 下一轮后端交付顺序

1. 工作流线确认下面的运行契约，首先补齐 knowledge 与步骤结果持久化。
2. 实现任务状态、查询、历史、中断记录和部分成功；保留现有独立 API 和同步 companion/run 的兼容行为。
3. 接入长文预算与分批，保留原文、稳定段落 ID、证据引用和批次结果。阅读、卡片、图谱分别验收，不能因 reading 分批通过就宣布另外两项也完成。
4. 提供 provider 通用的离线/模拟/真实 smoke；用户提供 DS 配置后先做五项小样本，随后做长文和故障恢复验收。
5. 知乎适配先固化来源身份、内容完整性和授权边界，再做公开接口的真实小样本同步。

当前共享目录已观察到长文及模型配置修改；其负责人应补充领取范围与测试回执，其他线不覆盖或复制实现。

## 运行 API 提案

| 端点 | 约定行为 |
| --- | --- |
| `POST /api/v1/runs` | 校验输入后 HTTP 202，返回 run_id 与 queued；重复客户端请求须有幂等键 |
| `GET /api/v1/runs/{run_id}` | 返回状态、各步骤进度、已保存 artifact 和脱敏错误；刷新或进程重启后可查询 |
| `GET /api/v1/runs` | 按来源、状态分页查询；列表不携带全部长文结果 |
| `POST /api/v1/runs/{run_id}/cancel` | 记录取消请求，停止后续调用；在途调用未结束前不伪报已取消 |
| `POST /api/v1/runs/{run_id}/retry` | 建立新运行，记录 parent_run_id；只复用满足版本条件的已成功结果 |

创建请求草案：

```json
{
  "source_id": "已导入的资料ID",
  "tasks": ["reading", "author", "cards", "facts", "knowledge"],
  "question": "作者如何说明这一结论？",
  "claims": ["要核查的明确主张"],
  "evidence_source_ids": ["可用证据资料ID"],
  "idempotency_key": "客户端生成的唯一请求ID"
}
```

同一幂等键且同一请求返回同一个 run；键相同但请求不同返回 409。author 需要 question，facts 需要 claims；非法任务或缺少参数在排队前返回 422。事实审查默认排除待核查资料本身。知识图的来源范围必须显式保存在运行输入中，不能在重试时悄然改成当前全部资料。

运行状态建议：`queued/running/cancelling/succeeded/partial_failed/failed/cancelled/interrupted`。步骤状态建议：`pending/running/succeeded/failed/skipped/cancelled/interrupted`。失败或取消仍可读取先前成功的 artifacts。服务重启将遗留的 running/cancelling 标为 interrupted，不自动发起新的收费模型请求。

每个 run 保存来源内容哈希、任务参数、provider/model、脱敏配置版本、prompt/schema 版本、时间和整体 deadline。每个 step 保存状态、尝试次数、批次进度、artifact_id、错误码、耗时及可获得的 token 用量。凭证不写 runs、artifacts、日志或报告；历史输出不能包含密钥。模型配置在单次运行中保持同一版本。

artifact 使用不可变 ID，保存能力类型、结果 schema 版本和来源/段落/证据 ID。原文未变、模型配置及 prompt/schema 版本一致时才允许复用；改变模型或材料会建立新的运行。真实上游没有返回 usage 时标为 unavailable，不能估算后冒充实际计费。

步骤失败的默认策略建议为继续其他独立任务，依赖失败的步骤标 skipped；终态区分全部成功、部分失败和全部失败。重试仅针对可重试的传输失败，设置次数、间隔、整体时限和调用预算。无效输入、无权限、证据校验失败不做盲目传输重试，也不静默切回离线成功。

## 五项能力统一验收

目标是模型可替换且业务契约一致。不能承诺任意模型具备相同推理质量。每个 provider/model 组合都必须分别通过结构、证据和质量门槛；未达标的能力明确标 unavailable、failed 或 insufficient_evidence，不能标为成功模型结果。

| 能力 | 必须自动验证 | 必须人工或标注集评估 |
| --- | --- | --- |
| 长文拆解 | 原文逐段保留，段落覆盖完整，不重复不漏段；批次和证据索引稳定 | 摘要覆盖主要论点、条件与限制，不把局部结论泛化 |
| 答主问答 | 作者和来源范围正确，引用序号与原文匹配；资料不足可拒答 | 回答切题，引用实际支持结论，不拼接成作者未表达的观点 |
| 记忆卡片 | 问答成对，证据为原文连续片段，去重，TSV/APKG 保留依据 | 一卡一个可学习知识点，问题与答案对应，避免空泛卡片 |
| 事实审查 | 排除自证，证据来源有效，主张逐条有结果 | 支持、反驳、条件不足和无法核验分开；来源存在不等于事实为真 |
| 知识图谱 | 节点/边去重，端点存在，证据 ID 有效，跨批合并可追溯 | 关系标签和方向正确，区分来源明示与模型推断 |

建议冻结一个至少 20 个情境的小样本集，覆盖常规输入、长文、否定、条件和数字、同义表达、冲突证据、缺证、资料内恶意指令和跨作者同名概念。至少 10 个情境覆盖每项能力；关键样本每个模型重复运行 3 次以观察波动。每条样本标 expected_status、关键事实/必要条件、合法证据范围及不允许的结论。

建议首轮门槛：结构与证据硬约束 100% 通过；有充分资料的正向样本不能靠全部拒答获得通过；每项能力语义合格率至少 90%，无依据的关键事实和作者越界为阻断项。门槛先记录，拿到真实输出后不能为凑通过率临时放宽。小样本结果不等于泛化质量保证。

报告分列 transport_ok、schema_ok、evidence_ok、semantic_ok、latency、usage、failure_class；模拟结果与真实模型结果分开。预算、超时、截断、空响应和 provider 参数能力也进入评测。支持 JSON 只保证输出格式，业务验证仍在后端。

## DS 接入准备

现有后端有 OpenAI-compatible Chat Completions 适配，但 B0 的 `ollama_smoke.py --live` 强制使用 Ollama，不能用它宣称 DS 已通过。下一轮提供显式 `--provider` 的通用验证命令后，再接收实际 Base URL、模型 ID 和预算。密钥在本地交互输入或进程环境中使用，不放进聊天、交接文件或代码；本轮没有接收密钥或调用真实模型。

DeepSeek 官方文档当前提供 `/chat/completions`，JSON 模式需要 `response_format={"type":"json_object"}` 并在提示中要求 JSON；还要处理输出截断与空内容。现有适配是否满足选定模型的全部参数，应由该模型的实际小样本验证确认。[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)，查询日期 2026-09-08。

## 知乎适配准备

已只读提取本地《知乎 OAuth 应用集成.docx》《知乎api接口及规范.docx》的接口说明；它们位于 `E:\CzCode\docx\codex\知乎api`。以下接口细节来自本地资料快照，尚未通过账号实测，实施前需核对当前官方文档与账号权限。在线检索找到官方数据开放平台，直接读取首页超时，不据此断定平台不可用。[官方平台](https://developer.zhihu.com/)。

本地资料列出了 `GET /api/v1/user/favlist_contents`，参数包括 FavlistUrlToken、Offset、Limit；使用 Access Secret，其他用户数据还涉及其 OAuth 授权。分页包含 IsEnd 和 NextOffset；适配器应使用服务端给出的下一页值，并防止重复游标死循环。先以调用方本人明确选择的公开收藏夹为试点，不假设一个用户的凭证能读所有用户资料。

关键限制是该资料中的收藏夹条目返回 **Summary 摘要**，Author 也可能缺失；搜索 ContentText 同样被描述为摘要。因此不能直接将其冒充文章全文，不能据此宣称完成长文拆解。作者缺失也不能把多个未知作者合并为同一个答主。全文获取方式和实际返回字段需先核实。

建议新增独立 ingestion 适配层和候选资料表，保存 `provider/external_id/content_type/original_url/canonical_url/fetched_at/content_hash/content_extent`，以及可确认的 external_author_id。保留原始来源 URL；规范化 URL 仅服务于去重。`content_extent` 区分 fulltext、excerpt、metadata，摘要/元数据不得未经显式处理进入全文能力。上述新字段不能直接发送到 B0 的 SourceDraft，B0 会拒绝未知字段；需要另立导入 schema 并由共享入口编辑者接入。

第一阶段只做用户选定资料的导入与增量更新：外部 ID 与本地 Source ID 建映射；正文变化产生新版本；同步状态在整页成功提交后推进；同页重试幂等；403/额度不足/频率限制与解析失败分别记录。保留来源和版本，不把文章删除或更新悄然改成旧结果对应的新证据。

悬浮球或桌面伴侣只需向后端提交用户明确选择的文本/来源或启动同步，再创建 run、查询进度和取结果。网页、桌面都复用同一套来源与运行 API。先定义 capture/ingestion 请求契约，不在本轮制作悬浮球，也不自动抓取任意网页或收集剪贴板。

## 每轮工作结果模板

在共享 CLI_HANDOFF.md 追加：日期与开发线；领取文件；实现/提案/未开始的状态；基于哪个提交及覆盖文件；测试命令、结果、证据路径与代码哈希；兼容性影响；下一阶段共享文件归属。最终验收以已保存快照为准，不用变化中的工作目录代替版本标识。
