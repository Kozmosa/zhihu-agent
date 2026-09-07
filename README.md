# 知境 ZhiJing Agent

v0.2 已为长文拆解、答主问答、记忆卡片、事实审查、知识地图接好模型生成适配器，支持 Ollama 原生 API 和 OpenAI 兼容 Chat Completions API。默认可离线运行；在首页输入模型配置，测试通过后即时启用。真实效果取决于模型输出质量，接通接口不等于完成效果评估。

项目正式入口是根目录的 **Start.cmd**，双击即可启动本地 Server，并在服务就绪后打开模型配置页。保留服务终端运行，按 Ctrl+C 停止。

## 入口和报告

| 文件 | 用途 |
| --- | --- |
| [Start.cmd](Start.cmd) | Windows 双击启动；自动选择项目虚拟环境 |
| [main.py](main.py) | 正式 Python 入口，支持参数和环境自检 |
| [运行测试报告.html](运行测试报告.html) | 双击打开，逐项查看案例、结果和实际响应 |
| [运行测试报告.md](运行测试报告.md) | 可在编辑器阅读的同内容报告 |
| [reports](reports) | 每次运行的原始日志、JUnit XML、响应和源码哈希 |
| [工程指南](ZhiJing-Agent-工程指南.md) | 功能分区、数据流与 API 契约 |
| [Ollama 接入说明](Ollama接入说明.md) | 五项能力接入、完整配置、模型限制与一键验证 |

## 启动方式

默认地址为 `http://127.0.0.1:8000/`，API 文档在 `/docs`。双击启动时解释器依次选择项目 `.venv`、`E:\CzCode\codex\envs\zhijing`、PATH 中的 Python；启动前检查依赖。

```powershell
# 在任意目录执行环境自检，不创建数据库或启动服务
& 'E:\CzCode\ZhiJing Agent\Start.cmd' --check

# 在任意目录指定端口启动
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\main.py' --port 8001
```

使用已安装依赖的解释器，也可在项目目录直接执行 `python main.py`。加 `--open-browser` 会在健康检查通过后打开浏览器。若端口被占用，选择其他端口，不会自动关闭已有服务。

首次使用请在 `POST /api/v1/sources/import` 导入 [examples/sources.json](examples/sources.json)，用响应中的 `source_id` 测试各接口；示例不会随启动自动写入数据库。也可运行 `scripts/demo.py`，它会导入同一组示例并调用统一工作流。

## 网页配置模型（新增）

访问 `http://127.0.0.1:8000/`，选择 **OpenAI 兼容 API** 或 **Ollama 原生 API**，填写 Base URL、模型 ID 和 API Key，然后点击 **测试并启用**。仅填写配置不会调用模型；测试会发送一条短请求，可能产生 API 用量。页面中的试读功能使用当前启用配置。

- OpenAI 兼容模式调用 `Base URL/chat/completions`，保留服务商给出的 `/v1` 或代理前缀，默认使用 JSON 模式。不支持 JSON 模式时，可在高级设置选择提示词约束；业务仍严格校验 JSON 和引用。不支持仅提供 Responses 或 Anthropic Messages 协议的地址。
- Ollama 模式继续使用原生 `/api/generate`。可在高级设置调整输出格式、超时、输出 tokens 和上下文预算。
- 页面输入的密钥仅保留在服务进程内存，接口不会返回密钥，不写 `.env`、数据库或浏览器 localStorage。启用成功后清空输入框；再次测试或修改配置需重新输入密钥，留空表示无鉴权。
- 配置即时生效，无需重启；失败保留当前配置。正在运行的业务请求继续使用原来的连接，结束后释放。可随时切回离线模式。
- 页面配置在服务重启后失效；重启仍读取启动环境变量。连接测试只确认短请求与 JSON 输出，不能代表五项业务的真实模型质量。
- 配置页仅允许本机访问，具备 Host、Origin 和页面令牌校验；保持默认 `127.0.0.1` 监听，不应作为公开管理接口部署。

也可使用 `ZHIJING_MODEL_PROVIDER=openai` 与 `ZHIJING_OPENAI_URL`、`ZHIJING_OPENAI_MODEL`、`ZHIJING_OPENAI_API_KEY` 启动。其他变量为 `ZHIJING_OPENAI_TIMEOUT`（120）、`ZHIJING_OPENAI_FORMAT`（json / prompt）、`ZHIJING_OPENAI_MAX_INPUT_CHARS`（120000）、`ZHIJING_OPENAI_MAX_TOKENS`（4096）、`ZHIJING_OPENAI_CONTEXT_WINDOW`（32768）。数字为默认值，需按服务商模型限制调整。

兼容协议依据：[DeepSeek Chat Completions 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。不同服务商的参数支持可能不同，需要使用自己的模型实测。

## 通过环境变量接入 Ollama

在同一个 PowerShell 终端设置环境变量后启动，已有服务需先停止再重启：

```powershell
$env:ZHIJING_MODEL_PROVIDER = 'ollama'
$env:ZHIJING_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZHIJING_OLLAMA_MODEL = '替换为服务端可用的模型名'
& 'E:\CzCode\ZhiJing Agent\Start.cmd'
```

地址填写服务基地址，允许末尾 `/api` 和代理前缀，不填写完整 `/api/generate` 或 `/api/chat`。Ollama 模式不能直接使用 OpenAI `/v1` API；兼容接口请使用首页的 OpenAI 兼容模式。`.env.example` 仅作参考，`.env` 不会自动加载。格式模式、可选密钥和上下文预算见 [接入说明](Ollama接入说明.md)。

五项结果通过 `mode` 区分 `extractive`、`ollama` 与 `openai`。没有可用证据时，问答、审查和地图会直接返回不足或空结果；模型错误会明确失败，不会静默切回规则。事实审查只解释当前证据与主张的关系，引用存在不等于判断正确或事实为真。

## 重新生成运行报告

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\run_report.py'
```

该命令依次运行全量 pytest、Ruff 检查、入口自检，并从项目外工作目录通过正式入口启动一次独立 HTTP 测试服务。结束后停止本次测试进程，更新根目录报告。原始证据保存在 `reports/时间戳/`，临时数据库位于 `E:\CzCode\codex\qa`，业务数据库不参与测试。

测试数量、结果和原始证据以更新后的 [运行测试报告](运行测试报告.md) 为准。自动化中的固定模型响应验证适配器及业务契约，不代表真实 LLM 效果。已有模型 API 的实际五项验证使用 `scripts/ollama_smoke.py --live`，完整命令见 [接入说明](Ollama接入说明.md)。真实知乎采集及 Anki 桌面导入仍未验证。

## 从云端仓库检出后运行

上面的绝对路径对应当前 CzCode 工作区。其他机器请在仓库根目录创建独立 Python 3.12 环境，并安装 `requirements-lock.txt` 中的依赖。Windows 示例：

```powershell
python -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
$env:ZHIJING_DATA_DIR = Join-Path (Get-Location) 'data'
& '.\Start.cmd'
```

其他系统可使用 `.venv/bin/python main.py`，并显式设置 `ZHIJING_DATA_DIR` 到可写目录。现有配置默认指向 CzCode 工作区；跨平台运行尚未实测。不要将个人 `.env`、数据库和虚拟环境提交到仓库，它们已加入忽略规则。

## GitHub 同步

目标仓库为 `https://github.com/Kozmosa/zhihu-agent`。先提交本地修改，并在执行终端完成 GitHub 认证，再运行项目内脚本：

```powershell
# 获取远端信息并输出同步计划，不合并或推送
& '.\scripts\sync_github.ps1'
# 合并远端默认分支、正常推送，再检查远端提交 SHA
& '.\scripts\sync_github.ps1' -Publish
```

脚本校验 origin 地址和干净工作区，自动读取远端默认分支；仅对空仓库采用 main。有冲突时保留现场并停止推送，不执行强制推送、清理或重置。它只对当前项目使用单次 Git 目录信任参数，不修改全局配置。若认证失败，需要在当前终端可用的 GitHub 登录环境中再执行。
