# ZhiJing Agent 后端开发结果

## 2026-09-09 恢复与 B2 验收

窗口关闭后的本地代码与日志仍完整。本轮核对资料库 B0、持久工作流 B1 和知乎表达 B2 的合并改动，将五个工作流/模型验收测试文件从本地临时目录复制到正式 `tests/`，保留原快照。完整测试不再依赖未提交的临时目录。`Test-Backend.ps1` 支持 `-Python` 和 `-WorkRoot`，默认使用当前 Python 环境。

记忆卡片、长文拆解、事实审查共同执行 `zhihu-knowledge-v1` 表达规范：保留条件、否定、来源与证据，不虚构个人资历或外部核验。新模型字段通过 Pydantic 限制长度，卡片拒绝相同问题与答案；原文、引文和历史导出契约保持完整。离线卡片明确是摘录草稿，超长完整句子跳过并说明，不截断证据。阅读多批摘要标记为按序汇集。

- 329 pytest 通过，2 个依赖弃用警告；Ruff lint 与 125 文件格式检查通过。
- 正式入口自检、14 个 HTTP 案例通过。
- extractive、Ollama mock、OpenAI-compatible mock 的五项能力与五步持久工作流全部通过，模型调用数为 0/10/10；幂等重放不新增调用。
- 工作台 DOM 处理函数和真实本地 HTTP 联调通过；skill 结构校验通过。
- 真实模型语义质量和浏览器视觉验收仍未执行。

本次完整日志保存在本机 `E:\CzCode\codex\qa\zhijing-recovery-20260909\checks-20260909-000639-278`，UI 日志在同级 `workspace`。仓库中的 B0/B2 历史证据继续保留；`src/.backend-work` 和 `src/_review` 是忽略的本地快照，不随应用发布。

复验命令：

```powershell
& 'E:\CzCode\ZhiJing Agent\src\Test-Backend.ps1' -Python 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -WorkRoot 'E:\CzCode\codex\qa\zhijing-backend'
```

下文为 2026-09-08 的 B1 历史结果，测试数量和发布状态均对应当时快照。

## B1 开发结果（历史记录）

2026 年 9 月 8 日。本轮按分工完成后端优化，资料库 B0 由另一开发线收尾，前端保持原状。

## 已完成

- **统一五能力工作流**：companion 已加入知识地图；新增 `/api/v1/runs` 创建、准备、执行、查询、分页、取消和重试接口。
- **运行与结果持久化**：SQLite 保存运行摘要、请求、来源 ID 快照、分步状态、结果及模型标签。成功能力不会因另一能力失败丢失；重试跳过成功能力。相同幂等键不重复生成，不同请求复用同键返回 409。
- **长文分批**：阅读、卡片和知识图使用同一预算预检；两种模型适配器的 1 万、3 万、10 万字符中文样本模拟测试通过。保留原文、段号和证据，卡片全局去重限量，图谱合并保留引用；超过 64 批在发请求前拒绝。
- **控制与恢复**：能力边界及每次模型调用前后检查取消和执行预算；启动时保留成功结果并标记中断任务，等待显式重试；配置切换不会误触发恢复。
- **模型验收**：新增 `verify_model.py`，支持 extractive、Ollama、OpenAI-compatible，分别记录传输与业务验证结果；可额外验收统一五步工作流、持久回读和幂等重放。DeepSeek 可明确设置思考模式，API Key 通过本机隐藏输入。

## 最终验证

| 检查 | 结果 |
| --- | --- |
| 全量测试 | 293 通过，2 个既有弃用警告，28.37 秒 |
| 静态与格式 | Ruff 通过，122 文件格式通过 |
| 入口与正式 HTTP | 自检通过，14/14 HTTP 案例通过 |
| 离线模式 | 五项独立能力及统一工作流通过，0 次模型调用 |
| Ollama 模拟服务 | 五项独立能力及统一工作流通过，共 10 次模型 HTTP 调用 |
| OpenAI-compatible 模拟服务 | 同上，共 10 次模型 HTTP 调用 |
| 幂等重复提交 | 两模型协议均未新增模型调用 |
| 真实 DeepSeek | 尚未执行，等待用户在本机输入密钥 |

唯一最终验收目录为 [checks-20260908-163336-805](.backend-work/checks-20260908-163336-805/summary.json)。目录内有日志、JUnit XML、三模式结果、源码哈希及可还原源码快照。早期试跑的失败记录保留，不应混作最终验收结果。

本轮以基准提交 `5d5104a8f4e12406755195f428b5a1dc5e955324` 和资料库 B0 为输入；没有修改存储开发线的六个文件。B0 的说明见 [资料库基线](../docs/backend/BASELINE.md)。B1 是本地验收快照，没有创建 Git tag、提交或发布。

## 直接使用

从任意 PowerShell 目录执行完整后端回归：

```powershell
& 'E:\CzCode\ZhiJing Agent\src\Test-Backend.ps1' -Python 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe'
```

准备好密钥后，执行 DeepSeek 的五项独立能力和统一工作流验收。命令只发送内置合成资料，通常共 10 次模型调用；密钥在提示时隐藏输入，不保存到项目。

```powershell
& 'E:\CzCode\ZhiJing Agent\src\Test-Backend.ps1' -Python 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -LiveDeepSeek
```

如仅需单独调用真实模型验收，不重跑完整测试：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' `
  'E:\CzCode\ZhiJing Agent\src\verify_model.py' `
  --provider openai --live --workflow `
  --url https://api.deepseek.com --model deepseek-v4-flash `
  --thinking disabled --prompt-key `
  --work-root 'E:\CzCode\ZhiJing Agent\src\.backend-work\deepseek-live' `
  --report 'E:\CzCode\ZhiJing Agent\src\.backend-work\deepseek-live\result.json'
```

模型 ID、标准 URL 及 thinking 参数已经与 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)核对。`thinking=auto` 不发送供应商扩展字段，可用于其他兼容接口。实际连接与模型输出仍以 live 结果为准。

## 下一步与当前边界

首先完成 DS live 验收，再用有标注的中文、矛盾证据和资料不足样本核对语义质量。软件已统一结构与证据约束，但不能保证任意模型的摘要或推理都正确；`quality_status=not_evaluated` 明确保留这一边界。

随后增加能力内部的分批结果保存，使长文中途失败只需重做失败批次；当前只复用成功的完整能力。阅读多批摘要目前为顺序汇集，图谱尚未额外推断跨批关系。

当前使用同步执行加可查询运行记录，同一数据目录只支持单应用进程。取消不能抢断已经发送的 HTTP 请求，须等其返回或传输超时。

知乎适配继续按 [知乎与桌面伴侣设计](../docs/backend/ZHIHU_ADAPTATION.md)推进。协作线的本地文档记录提示收藏夹内容可能只有摘要，因此下一阶段先实现有 content_extent 的候选导入契约、外部 ID 与不可变来源版本映射，再按核实的官方权限接入采集。桌面伴侣将复用现有来源和 runs 接口；本轮未制作悬浮球或其他前端。

日常进度、文件归属及测试记录见 [后端开发记录](BACKEND_WORKLOG.md)，完整接口契约见 [持久工作流说明](zhijing/features/runs/README.md)。
