# 知境 v0.2：Ollama 接入说明

长文拆解、答主问答、记忆卡片、事实审查、知识地图均已接入共享的 Ollama 适配器。默认 `extractive` 模式仍可离线使用。准备好可用的 Ollama 原生 API 和模型后，设置环境变量并重启知境即可调用；模型必须返回符合约定的 JSON 与引用结构，接口连通本身不保证任务成功。

## 1. 在当前终端配置并启动

以下配置只影响当前 PowerShell 终端及它启动的进程。也可把变量写进项目根目录的 `.env`（参照 `.env.example`），源码运行时启动自动读取，进程环境变量优先；打包桌面版不读取。修改变量不会更新已经运行的服务，需要停止原服务并重启。

```powershell
$env:ZHIJING_MODEL_PROVIDER = 'ollama'
$env:ZHIJING_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZHIJING_OLLAMA_MODEL = '替换为服务端可用的模型名'
$env:ZHIJING_OLLAMA_TIMEOUT = '120'
$env:ZHIJING_OLLAMA_FORMAT = 'schema'
$env:ZHIJING_OLLAMA_MAX_INPUT_CHARS = '120000'
$env:ZHIJING_OLLAMA_NUM_PREDICT = '4096'
$env:ZHIJING_OLLAMA_NUM_CTX = '32768'
& 'E:\CzCode\ZhiJing Agent\Start.cmd'
```

如果接口需要鉴权，在启动前设置可选变量 `ZHIJING_OLLAMA_API_KEY`，适配器会发送 `Authorization: Bearer ...`。只在本地终端中提供密钥，不写进示例、报告、Git 或 URL。无鉴权的本地服务无需该变量。

`Start.cmd` 和 `main.py` 均可从任意目录调用。也可用项目解释器执行：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\main.py' --check
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\main.py' --port 8001 --open-browser
```

自检检查环境与配置，不会调用模型。`/health` 报告配置的供应商，不代表远端模型可用。启动后打开 `http://127.0.0.1:8000/docs`；指定 8001 时相应更换端口。

## 2. 地址与输出格式

适配器使用 **Ollama 原生 `/api/generate`**，请求采用非流式 `system`、`prompt` 和 `options`，响应读取 `response` 字段。它不是任意 OpenAI `/v1/chat/completions` 接口的适配器。

| `ZHIJING_OLLAMA_URL` 示例 | 最终请求路径 |
| --- | --- |
| `http://127.0.0.1:11434` | `/api/generate` |
| `http://127.0.0.1:11434/api` | `/api/generate` |
| `https://model.example.com/ollama` | `/ollama/api/generate` |
| `https://model.example.com/ollama/api` | `/ollama/api/generate` |

填写服务基地址，不填写完整 `/api/generate`、`/api/chat` 或 `/chat/completions`。支持代理路径前缀；URL 不允许带用户名、密码、查询参数或 fragment。代理端也必须实现兼容的 Ollama 原生请求和响应。

| `ZHIJING_OLLAMA_FORMAT` | 实际行为 |
| --- | --- |
| `schema`，默认 | 向 `format` 发送 JSON Schema，同时把 Schema 放入 prompt |
| `json` | 发送 `format: "json"`，prompt 仍包含具体 Schema |
| `prompt` | 不发送 `format`，仅在提示中要求符合 Schema 的 JSON |

三种模式都使用严格 JSON/Schema 校验，并继续检查真实引用、段落索引或图结构。`prompt` 不会接受 Markdown 代码块、解释性前言或格式错误的普通文本。模式不会自动切换，失败也不会自动回退离线规则。

Ollama 官方文档目前注明 **Cloud 不支持 structured outputs**。若服务端不支持 `format`，可明确选择 `prompt` 尝试，但仍要求模型输出合规 JSON，不能保证云端接口或任意模型必然可用。该限制核查于 2026-09-07，参见 [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)。

## 3. 超时与输入预算

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ZHIJING_OLLAMA_TIMEOUT` | `120` | 单次模型 HTTP 调用超时，秒 |
| `ZHIJING_OLLAMA_MAX_INPUT_CHARS` | `120000` | 完整 system 与 prompt 的字符预算 |
| `ZHIJING_OLLAMA_NUM_PREDICT` | `4096` | 请求给模型的最大生成长度 |
| `ZHIJING_OLLAMA_NUM_CTX` | `32768` | 请求给模型的上下文大小及本地预算上限 |

字符预算包括任务指令、完整资料、JSON 编码结构和 Schema，不只计算正文。服务还检查 `UTF-8(system + prompt) 字节数 + NUM_PREDICT + 512 <= NUM_CTX`。这是保守估计，**不是真实模型 tokenizer**，可能比模型实际容量更早拒绝输入，也不替代服务端上下文检查。

任一预算超限返回 HTTP 413、`model_input_too_large`，不会发出模型请求，不会静默截断正文。可缩小资料范围，或在模型及服务确实支持的范围内调整预算。只提高 `MAX_INPUT_CHARS` 不会绕过上下文限制；只增大 `NUM_PREDICT` 会减少留给输入的空间。

阅读和制卡保留所选完整正文；地图保留 `limit` 内所选资料的全部分块，并用 `total_sources`、`truncated` 报告资料范围。问答与事实审查采用检索候选证据，这属于明确的检索范围，不等同于全文推理。单篇资料可导入的长度上限与一次模型调用的容量是两项不同限制。

## 4. 五项能力如何使用模型

| 能力 | 模型参与和服务校验 |
| --- | --- |
| 长文拆解 | 服务端先分段，模型生成摘要、段标题、要点、导读问题；每个原文段落索引必须恰好出现一次，原文由服务回填 |
| 答主问答 | 向模型提供该作者的检索上下文，要求答案带 `[n]` 引用；编号须来自提供的上下文并与模型声明一致 |
| 记忆卡片 | 根据指定资料生成独立问题、答案和逐字证据摘录；检查数量、重复问题、摘录是否属于原文，来源 ID 由服务赋值 |
| 事实审查 | 根据实际检索证据判断支持、反驳、混合或不足，说明引用理由与适用条件；检查结论和证据关系一致，并遵守作者及排除来源条件 |
| 知识地图 | 提取概念及受限关系，生成 XYFlow 的 nodes/edges/position；检查唯一 ID、端点和证据编号，真实引用由服务回填 |

五项结果都通过 `mode` 标明实际路径：`extractive` 为规则或摘录，`ollama` 为模型生成。事实审查中多个主张至少一个调用模型时，整体 mode 为 `ollama`；没有证据的主张仍直接返回不足。无资料地图、无证据问答和审查不调用模型；阅读或制卡的 `source_id` 不存在时直接返回 404。

事实审查的 `supported_by_evidence`、`refuted_by_evidence`、`mixed_evidence` 描述的是**当前语料与主张的语义关系**，不是客观真伪认证。未找到证据也不能证明主张为假。离线状态仍为 `mentioned_in_corpus`、`related_evidence`、`insufficient_evidence`。

答主接口的 `citations` 返回完整输入上下文，答案中的 `[n]` 对应列表第 n 条；列表不是“模型实际逐条使用的引用清单”。指定主资料会主动将其中一个片段放入上下文，不能把它的出现视为独立支持。

卡片返回的 `evidence_excerpt` 在 TSV 与 APKG 导出中随来源信息保留，仍保持 Front、Back、Source 三字段兼容。编号、ID 和摘录校验只能排除不存在的引用，不能证明模型的解释、卡片答案或关系推断正确。内容质量仍需人工检查。

## 5. 导入资料和验证

首次使用，在 Swagger 的 `POST /api/v1/sources/import` 提交 [examples/sources.json](examples/sources.json) 的完整 JSON，用返回的实际 ID 调用五项功能。启动服务不自动导入。也可从任意目录运行演示脚本；脚本会读取同一文件并导入合成资料：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\demo.py' --url http://127.0.0.1:8000
```

已有真实模型 API 后，在已设置模型配置的终端运行五项验证，无需手动再启动另一个知境服务：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\ollama_smoke.py' --live --timeout 120 --work-root 'E:\CzCode\codex\qa' --report 'E:\CzCode\codex\qa\zhijing-ollama-live.json'
```

脚本读取 `ZHIJING_OLLAMA_URL` 和 `ZHIJING_OLLAMA_MODEL`，也允许用 `--url`、`--model` 覆盖；密钥及其他模型配置继承当前终端。脚本的 `--timeout` 独立控制本次测试超时，默认 120 秒。它通过正式 `main.py` 启动临时端口的服务，使用隔离数据库导入合成测试资料，调用全部五项，结束后只停止本次测试进程。退出码 0 表示检查通过，非 0 时查看报告中的失败项目和错误码。

没有模型 API 时，可以只检查接线：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\ollama_smoke.py' --mock --work-root 'E:\CzCode\codex\qa' --report 'E:\CzCode\codex\qa\zhijing-ollama-mock.json'
```

`--mock` 使用本地固定响应服务器，不运行 LLM，也不消耗真实模型 API；`--live` 才调用配置的实际模型。两者使用的测试资料都是合成资料。mock 成功证明接线和校验可用，不能作为模型理解、推理或事实核查效果的证据；live 成功同样只是一次功能冒烟检查。

完整自动化案例、实际通过数量及运行证据见 [运行测试报告](运行测试报告.md)。

## 6. 常见响应

| HTTP / 错误码 | 检查方向 |
| --- | --- |
| `413 / model_input_too_large` | 减少资料或在服务支持范围内调整字符、上下文预算 |
| `502 / model_timeout` | 确认模型运行状态；必要时同时增加模型调用和测试脚本超时 |
| `502 / model_unavailable` | 检查原生 API 基地址、模型名、可选鉴权、服务状态 |
| `502 / model_invalid_response` | 检查输出格式、生成长度、引用、段落覆盖和图结构；不接受不合规输出 |
| `422` | 按 Swagger Schema 检查请求，阅读的 text 与 source_id 二选一 |
| `404 / source_not_found` | 先导入资料，再使用导入响应中的 ID |

切回离线时设置 `$env:ZHIJING_MODEL_PROVIDER = 'extractive'` 并重启。模型故障不会自动切回离线，避免把失败误报为成功。
