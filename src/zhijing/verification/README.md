# 后端模型验收

本模块用两篇手写合成资料，逐项调用阅读、卡片、事实审查、知识地图和作者问答的公开 API。任一能力失败仍继续检查其余能力。它验证接口连接、结构与证据约束，不能证明任意模型都具有足够的语义质量，也不把语料支持等同于客观事实。

## 运行

未安装项目包时，从 `E:\CzCode\ZhiJing Agent\src` 执行下列命令；`python` 应使用项目环境 `E:\CzCode\codex\envs\zhijing\Scripts\python.exe`。也可以使用 `src/verify_model.py` 从其他目录启动。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -m zhijing.verification --provider extractive --mock --work-root .backend-work/20260908/verification-work --report .backend-work/20260908/evidence/verify-extractive.json
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -m zhijing.verification --provider ollama --mock --work-root .backend-work/20260908/verification-work --report .backend-work/20260908/evidence/verify-ollama.json
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -m zhijing.verification --provider openai --mock --work-root .backend-work/20260908/verification-work --report .backend-work/20260908/evidence/verify-openai.json
```

模型协议的 `--mock` 启动随机端口的 localhost HTTP 服务，走真实 Ollama `/api/generate` 或 OpenAI `/v1/chat/completions` 请求与解析路径；它不调用远端模型。`extractive --mock` 只做离线检查。临时业务数据库独立创建并在检查后清理，不读取或修改正在使用的资料库。

只有明确指定 `--live` 才会访问配置的模型服务。可从 `ZHIJING_OPENAI_*` 或 `ZHIJING_OLLAMA_*` 环境变量读取配置，也可以用 `--url`、`--model`、`--timeout` 覆盖。密钥只从环境变量或 `--prompt-key` 的隐藏输入获取，没有 API Key 命令行参数。隐藏输入不可用时直接失败，不降级成回显输入。

DeepSeek 首轮结构化验收的待执行命令：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' -m zhijing.verification --provider openai --live --url https://api.deepseek.com --model deepseek-v4-flash --thinking disabled --prompt-key --work-root .backend-work/20260908/verification-work --report .backend-work/20260908/evidence/verify-deepseek-live.json
```

以上真实接口命令需要用户在自己的终端输入密钥；此次开发没有执行真实模型调用。`--thinking auto` 不发送额外的 thinking 字段，适用于普通 OpenAI 兼容端点。

增加 `--workflow` 可同时检查持久化工作流的五个阶段、GET 结果回读与相同幂等键重复提交；重复提交不能产生额外模型调用。此选项在五项独立检查之外通常增加五次模型调用，默认关闭。它不会测量前端体验、进程重启恢复或并发取消，后两项由工作流专项回归测试覆盖。

## 读取报告

- `cases` 始终包含五项，分别记录 `status`、`reason`、`response_mode` 和 `application_validation_passed`。准备阶段失败时保留五项 `not_run`。
- `transport` 分开记录请求数、收到 HTTP 响应的数量及 HTTP 成功数。上游 HTTP 200 但证据校验被拒绝时，传输成功，能力仍失败。
- `passed` / `admission=smoke_passed` 仅表示该组合通过本次合成样例准入；不构成生产质量准入。静默退回其他 provider 的结果不计为目标模型成功。
- `quality_status` 固定为 `not_evaluated`。报告不保存来源全文、模型输出、完整 URL、HTTP 请求头或密钥；后续语义质量验收仍需单独的人工标注材料。
- 退出码 `0` 表示全部检查通过，`1` 表示配置或能力失败，`2` 表示命令行使用错误或报告写入失败。

合成 fixture 改编自本仓库 `scripts/ollama_testing/fixtures.py`，运行时不依赖 `scripts` 目录。回归测试位于 `tests/test_provider_verification.py`，包含在默认 `python -m pytest` 测试集中。
