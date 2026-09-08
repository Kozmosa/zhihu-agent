# ZhiJing Agent 后端开发记录

## 2026-09-09 恢复并准备合并

从仍保留的工作树、B0/B1/B2 结果和上一轮会话确认任务：完成阅读、记忆卡片、事实审查的知乎表达约束后合并云端。本轮保留所有既有应用改动与历史快照，领取集成收尾和发布范围；没有另启并发开发线。

将 batching、model_contract、provider_verification、runs、runtime_recovery 五个回归测试文件复制到正式 tests，修正 CLI 子进程工作目录；完整验收脚本不再依赖 src 下的临时测试。忽略本机 review/checks 快照，维护入口文档与最新结果说明。

验证：329 pytest、Ruff lint/125 文件格式、正式入口、14 HTTP、三种模式的五能力/持久工作流、工作台 DOM/HTTP 联调及 skill 校验全部通过。QA 根目录为 `E:\CzCode\codex\qa\zhijing-recovery-20260909`。未调用真实模型。

Git 远程访问复现 git-remote-https.exe 崩溃；项目原有 http.sslBackend=openssl 覆盖已移除，恢复安装级 schannel。恢复后远程命令以明确 SEC_E_NO_CREDENTIALS 错误退出，不再弹内存崩溃框；当前受限会话无法完成 Windows TLS 凭据初始化。普通 PowerShell 的远程访问需用户对照验证，不能把本地提交记作已推送。

## 2026 年 9 月 8 日 开始后端优化

用户确认按既有文档分工开发，当前不制作或调整前端。产品方向为悬浮球或桌面伴侣，后端继续服务长文拆解、答主问答、记忆卡片、事实审查、知识地图五项核心能力。

### 已固定的输入基线

- 本地 HEAD：`5d5104a8f4e12406755195f428b5a1dc5e955324`，分支 `feat/knowledge-workspace-ui`，包版本 `0.2.0`。
- 包含已有未提交资料库改动和三处 UI 改动。它们来自本轮之前及另一个进程，本开发线保留原状。
- 最近完整验收：210 pytest、14 离线 HTTP、5 项 Ollama mock、工作台联调通过，Ruff 通过。
- 可还原基线增量：`.backend-work/20260908/evidence/baseline.patch`；未跟踪测试副本为 `baseline-test_source_storage.py`，哈希见 `baseline-hashes.json`。应用于上述 HEAD 即可还原此次开发的输入代码基线；未创建 Git 标签或提交。

### 文件分工

| 开发线 | 负责范围 | 当前状态 |
| --- | --- | --- |
| 另一个命令行助手 | 资料仓储、sources 服务和路由、来源领域契约、存储测试与搜索说明 | 保留其改动，当前开发线不重写 |
| 工作流 | companion 五能力、runs 状态与结果、SQLite 运行记录、部分失败和恢复 | 本轮完成，27 项专项通过 |
| 长文处理 | 阅读、卡片、知识图分批与合并、全量预算预检 | 本轮完成，33 项专项通过 |
| 模型验收 | 模型无关验证 CLI、两协议 mock、用户输入 key 的 live 入口 | 本轮完成，16 项专项通过，live 待密钥 |
| 集成与记录 | container/api/runtime、共同预算检查、DeepSeek 参数、测试与知乎适配设计 | 本轮完成，全量验收通过 |

开发开始时，共享的 `domain/models.py` 与 `domain/ports.py` 由资料库开发线管理；本轮采用独立 schema，未修改这两个文件。资料库线完成 B0 后已在交接回执中将下一阶段共享入口的唯一编辑权交给工作流线。所有新增测试位于 `.backend-work/20260908/tests`，因为本会话仅允许写入 src。最终需同时运行原 tests 与该目录测试。

### 已落实的集成变化

- 模型生成器增加 `check_budget`，与真实 generate 共用同一份包含系统提示、schema 和输出余量的检查；预检不发网络请求。
- OpenAI-compatible 增加可选 `thinking=auto/enabled/disabled`，默认 auto 不附加供应商扩展参数。可通过 `ZHIJING_OPENAI_THINKING` 或本机配置 API 使用，不修改页面。
- 用户指定 DeepSeek 标准地址、`deepseek-v4-flash`。API Key 尚未输入；真实模型请求和质量验收尚未开始。

### 本轮验收目标

五项独立能力保持兼容；统一运行包含 knowledge；运行及分步结果可持久化、查询、取消和有限重试；长文在默认预算下分批处理且保留原文证据；两种模型协议有统一验收入口。同步执行和取消检查点的实际限制必须在结果文档中说明。

### 外部接口核对

DeepSeek 官方文档确认标准 OpenAI 格式地址为 `https://api.deepseek.com`，`deepseek-v4-flash` 支持 JSON 输出；思考模式默认启用，可显式切换。首轮结构化 smoke 建议使用 disabled，后续再比较 enabled 的质量与时延。

来源：[模型信息](https://api-docs.deepseek.com/quick_start/pricing/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)，核对日期 2026-09-08。

知乎开发者首页本次工具访问超时，候选收藏夹文档 URL 被工具拒绝；尚未取得可核对的鉴权及响应 schema。不能据此断言知乎平台不可用，也不把猜测的接口写成正式采集实现。适配先确定桌面伴侣可提交的原文、来源标识与作者信息契约，详情见后续适配设计。

### 完成记录 工作流 B1

最终验收于 2026-09-08 16:34 +08:00 完成：293 pytest 通过，2 个既有依赖弃用警告；Ruff lint 通过、122 文件格式通过；正式入口自检与 14 个独立正式 HTTP 案例通过。extractive、Ollama mock、OpenAI-compatible mock 均通过五项独立能力和五步持久工作流，模型调用数分别为 0、10、10，幂等重放没有新增调用。

结果与证据位于 `.backend-work/checks-20260908-163336-805/summary.json`、各 provider JSON、pytest.xml、source-manifest.json。此前试跑的测试夹具数组类型错误和 Ruff 中文差异展示崩溃均已修正；最终脚本使用 concise 格式输出，并完整重跑所有检查。旧失败日志保留，最终结果只以上述新目录为准。

阶段成果：新增 `runs.sqlite3`，在 runs 表中保存摘要及包含步骤和结果的 JSON；每能力单独原子提交，模型请求期间不持有写事务。支持先创建任务拿 ID、查询/分页、执行/取消/有限重试、重启中断标记，以及语料成员快照。重试保留成功能力，未完成能力使用当前配置并记录各步骤模型标签。已修复取消与最终完成竞争时取消状态被忽略的问题。

长文按预算处理所有批次；最多 64 批，超出在网络请求前明确拒绝。阅读摘要是各批汇集；知识图尚不额外推断跨批关系。持久化仍以能力为单位，中途失败会重做该能力内部批次；已经发出的 HTTP 无法抢断。同一数据目录仍要求单应用进程。

协作线已交付 `../docs/backend/BASELINE.md` 中的 `storage-B0-20260908`，六个资料库文件哈希与本轮输入一致，本开发线没有覆盖其实现。其 `NEXT_CONTRACT.md` 还给出了本地知乎 DOCX 的提取结论：收藏夹接口资料可能仅含 Summary 摘要，作者也可能缺失。该信息已纳入适配设计；官方接口与账号权限仍未实测。

完整本轮结果见 `BACKEND_RESULT.md`。当前未提交或推送代码，未调用真实模型，未改业务数据库，未改前端。本轮 B1 是本地验收快照，不是已发布版本或 Git tag。
