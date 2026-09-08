# 持久化五能力工作流

本轮后端基线（2026-09-08）：保留同步调用，新增可先拿到任务 ID 的两阶段接口。每个能力完成后提交 SQLite，后续能力失败不会丢失已完成结果。所有接口均位于 `/api/v1`，依赖当前请求已有的 runtime lease，无隐藏后台线程。

## 桌面伴侣推荐调用顺序

1. 导入资料，取得 `source_id`。
2. `POST /runs`，请求头提供 `Idempotency-Key`，正文设置 `prepare_only: true`，立即得到 `id` 和 `pending`。
3. 在独立请求中 `POST /runs/{id}/execute`；该请求同步等待执行结束。
4. 执行过程中可用另一请求 `GET /runs/{id}` 查询步骤状态，或 `POST /runs/{id}/cancel` 请求取消。
5. 部分失败、取消、超时或进程中断后，使用 `POST /runs/{id}/retry`。成功步骤保留，其他步骤重新执行。

示例请求（`source_id` 替换为已导入资料 ID）：

```http
POST /api/v1/runs
Content-Type: application/json
Idempotency-Key: desktop-session-001

{
  "source_id": "YOUR_IMPORTED_SOURCE_ID",
  "tasks": ["reading", "cards", "facts", "author", "knowledge"],
  "question": "这个观点成立的条件有哪些？",
  "claims": ["需要根据独立资料核对的明确主张"],
  "knowledge_scope": "author",
  "knowledge_limit": 100,
  "prepare_only": true,
  "timeout_seconds": 600,
  "max_attempts": 3
}
```

省略 `prepare_only` 时，创建接口会同步完成本轮执行再返回。省略 `tasks` 时运行阅读、卡片、知识地图；问答和事实审查分别需要显式提供 `question`、`claims`。

| 接口 | 行为 |
| --- | --- |
| `POST /runs` | 幂等创建；可同步执行或只准备 |
| `POST /runs/{id}/execute` | 仅启动 `pending` 任务 |
| `GET /runs/{id}` | 完整请求、语料 ID 快照、步骤状态和结果 |
| `GET /runs?offset=0&limit=20` | 分页摘要，不加载全部大结果；支持 `source_id`、`status` 过滤 |
| `POST /runs/{id}/cancel` | 待执行任务立即取消；执行中设置取消请求 |
| `POST /runs/{id}/retry` | 仅重跑未成功步骤；正在执行或次数耗尽返回 409 |

幂等键为 1 至 128 个字母、数字或 `._:-` 字符。相同键与相同请求返回已有任务，不重复调用模型；相同键用于不同请求返回 `idempotency_conflict`（409）。数据库只保存键的 SHA-256 摘要。改变输入、预算或能力组合，需要创建新任务并使用新键。

## 范围、结果和模型切换

- 阅读和制卡针对主资料；答主问答只使用主资料所属答主的历史资料，并优先包含主资料。
- 事实审查使用创建时已导入的语料，但始终排除主资料，避免把待核查文章自身当作独立依据；结果是语料与主张的关系，并非客观真实性证明。
- `knowledge_scope: author` 仅组织同一答主资料；`library` 组织当时的整个资料库。`knowledge_limit` 控制选取上限，图中的 `truncated` 明示截断。主资料并不保证在超出上限后的图内，图的选择按固定资料 ID 顺序。
- 创建时保存必要范围的内容寻址资料 ID 快照。后续导入的新资料不会混入原任务；重试仍使用原快照。
- 顶层 `provider` / `model` 是创建时配置标签；步骤的标签记录该步骤最近一次实际尝试所使用的配置。重试可以使用当前新的模型配置，成功步骤的结果与标签不会改写。结果内部的 `mode` 保留实际分析模式，例如证据不足时的 `extractive`。
- 配置记录仅保存脱敏标签，不保存模型 URL、API key 或原始上游错误正文；输入问题、主张和生成结果属于任务正文，保存在本地任务数据库。

## 状态、控制和恢复

任务状态包括 `pending`、`running`、`succeeded`、`partial`、`failed`、`interrupted`、`cancelled`、`timed_out`。单步骤状态另有 `pending`、`running`、`succeeded`、`failed`、`interrupted`、`cancelled`。所有记录时间使用 UTC ISO 8601。

`timeout_seconds` 是每轮执行的协作时间预算，默认 600 秒、范围 1 至 3600 秒；`max_attempts` 是整个任务累计执行轮数上限，默认 3、范围 1 至 5。仅准备任务不消耗次数，执行或重试消耗一次。失败不会自动反复调用模型，用户或调用端明确重试后才继续。

取消和时间预算在能力边界、每次模型 `generate` / `answer` 调用前后检查，包含长文分批和多主张事实分析。已经发出的 HTTP 调用不能强行中断，要等当前请求返回或其传输超时；控制检查不会启动下一次模型调用。极短竞态下取消前已算出的结果可以保留，但已接受取消的任务最终状态保持 `cancelled`。

应用首次启动时，将数据库中上次遗留的 `running` 标为 `interrupted`，保留成功结果，等待显式重试。只准备的 `pending` 保持原状态。模型配置热切换不会触发恢复。当前恢复机制要求**同一数据目录只运行一个应用进程**；不要使用多个 Uvicorn worker 共同打开同一个工作流数据库。

## 当前持久化边界与验收

持久化单位是能力步骤。长文一个能力内部的多个模型批次尚未逐批保存；中途失败后会重做该能力，但不会重做之前成功的能力。模型已返回、SQLite 尚未提交时发生进程崩溃，重试可能再次产生上游调用；本地幂等并不承诺上游服务的严格一次执行。

功能测试位于 `tests/test_runs.py`，覆盖五能力统一结果、幂等冲突、独立失败与重试、模型标签保留、两阶段创建、并发查询与取消、超时、重启恢复、语料快照、列表摘要、参数校验与错误脱敏。真实模型连接及业务结构由独立验收工具验证；语义质量仍需要标注样本与人工复核。
