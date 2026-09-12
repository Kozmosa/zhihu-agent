# 知境 ZhiJing Agent

v0.2 已为长文拆解、答主问答、记忆卡片、事实审查、知识地图接好模型生成适配器，支持 Ollama 原生 API 和 OpenAI 兼容 Chat Completions API。默认可离线运行；在首页输入模型配置，测试通过后即时启用。真实效果取决于模型输出质量，接通接口不等于完成效果评估。

项目正式入口是根目录的 **Start.cmd**，双击即可启动本地 Server，并在服务就绪后打开模型配置页。保留服务终端运行，按 Ctrl+C 停止。

## 入口和报告

当前后端支持五能力持久运行、部分失败后的显式重试，以及阅读、卡片、知识图谱的长文分批处理。运行接口见 [runs 契约](src/zhijing/features/runs/README.md)。阅读、卡片、事实审查使用 [知乎知识回答表达规范](skills/zhihu-knowledge-answer/SKILL.md)，对新模型结果执行长度和证据约束；模型语义质量仍需真实样本验收。

在装有开发依赖的 Python 3.12+ 环境中运行 `python -m pytest` 即可执行完整回归测试。Windows 完整后端验收使用 `powershell -NoProfile -File src/Test-Backend.ps1 -Python <项目Python路径>`，涵盖静态检查、正式 HTTP 入口与三种 provider 的离线/模拟工作流；真实模型须单独显式启用。验证结果默认写入本地忽略目录 `src/.backend-work`，可用 `-WorkRoot` 指定位置。

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

默认地址为 `http://127.0.0.1:8000/`，API 文档在 `/docs`。双击启动时解释器依次选择项目 `.conda`、`.venv`、相邻 `codex\envs\zhijing`、PATH 中的 Python；启动前检查依赖。未设置 `ZHIJING_DATA_DIR` 时，`Start.cmd` 使用项目内的 `data` 目录。

```powershell
# 在任意目录执行环境自检，不创建数据库或启动服务
& 'E:\CzCode\ZhiJing Agent\Start.cmd' --check

# 在任意目录指定端口启动
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\main.py' --port 8001
```

使用已安装依赖的解释器，也可在项目目录直接执行 `python main.py`。加 `--open-browser` 会在健康检查通过后打开浏览器。若端口被占用，选择其他端口，不会自动关闭已有服务。

首次使用请在 `POST /api/v1/sources/import` 导入 [examples/sources.json](examples/sources.json)，用响应中的 `source_id` 测试各接口；示例不会随启动自动写入数据库。也可运行 `scripts/demo.py`，它会导入同一组示例并调用统一工作流。

## 知识工作台（新增）

启动后，在模型配置页点击 **进入知识工作台**，或访问 `http://127.0.0.1:8000/workspace`。

工作台支持 **搜索知乎 → 预览结果 → 导入摘要**。点击左侧“搜索知乎”，在面板中配置知乎开放平台的 Access Secret（仅保留当前服务会话），输入关键词后选择结果导入。也可在启动服务前设置 `ZHIHU_ACCESS_SECRET`。返回的是官方搜索摘要，页面和资料库均会标明；不提供任意链接全文抓取。配置与导入不额外发起搜索，点击搜索会使用平台额度。详见 [知乎搜索接入与测试](docs/zhihu-search.md)。

1. 点击 **导入资料**，填写标题、作者名称、作者 ID 和原文；可选填写来源链接与主题。来源链接用于追溯，不会自动抓取网页。同一作者使用相同 ID。
2. 在资料库选择一篇文章。支持按作者 ID 筛选和分页，也可从 JSON 文件批量导入项目示例格式的数据（一次最多 20 条）。
3. 切换五个能力页签：长文拆解保留原文对照；答主问答引用当前文章及同作者资料；记忆卡片可查看答案和依据并导出 TSV/APKG；事实审查可选择语料范围并排除当前文章；知识地图可点击节点或关系查看解释和证据。
4. 问答和卡片需要先选择资料。事实审查及地图可面向全部资料库；语料不足会明确提示，不会假定存在证据。

工作台和模型配置页均有右下角 **问知境** 悬浮球，浮窗中可独立选择资料并查看答案引用。同一浏览器标签页切换页面会恢复所选资料；只在会话存储中保存资料 ID，聊天记录不跨页面保存。每条问题独立依据已导入资料回答，不会把之前的聊天记录发送给模型。手机端可展开“我的资料”选择文章。

需要关闭浏览器后仍能提问时，双击项目根目录的 **StartDesktop.cmd** 启动桌面悬浮助手。它使用项目 Conda 的 Tkinter，无需打开网页：刘看山悬浮图标始终置顶，可拖动位置；单击打开独立问答窗，选择资料后输入问题。关闭问答窗或按 Esc 只收起窗口，右键悬浮图标选择“退出”才结束助手。也可以从右键菜单打开工作台和模型配置页。已运行的本地服务会被复用；没有服务时助手自动启动本地服务，并在退出时停止自己启动的服务。资料保存在原数据目录，退出不会删除。

桌面环境检查：在项目目录运行 `.conda\python.exe desktop.py --check`。默认端口为 8000；自定义端口可运行 `StartDesktop.cmd --port 8001`。桌面助手无需浏览器存活，但助手进程及其连接的本地服务需要保持运行。默认不会设置系统开机自启动。

## Windows 桌面软件

免安装版包含 Python、Tcl/Tk、本地服务和页面资源。解压整个软件包后，双击 **知境.exe** 即可使用，无需安装 Python 或 Conda。请保留旁边的 `_internal` 文件夹。关闭浏览器不影响悬浮助手；关闭问答窗只收起窗口，右键刘看山选择“退出桌面助手”才退出软件。

软件版默认把资料保存在 `%LOCALAPPDATA%\ZhiJing\data`，更新时可以替换软件目录而保留资料。源码启动仍默认使用项目 `data`。两种入口均支持用绝对路径 `ZHIJING_DATA_DIR` 指向同一份资料；软件包不包含个人资料或密钥。页面填写的模型和知乎密钥仅在当前服务会话有效，重启后需重新配置。未配置模型时使用现有离线模式。

开发者在 Windows、Python 3.12 环境中可从仓库根目录构建：

```powershell
python -m pip install -r requirements-lock.txt
python -m pip install pyinstaller==6.22.0
python scripts/build_desktop.py
```

默认产物为 `dist\知境\知境.exe`，将整个 `dist\知境` 文件夹压缩即可分发。已有产物时需显式传入 `--overwrite`。构建报告在 `build\desktop\build-report.json`。自检不会打开窗口或创建资料库，窗口版 EXE 用文件输出报告：

```powershell
Start-Process '.\dist\知境\知境.exe' -ArgumentList '--check', '--check-report', 'desktop-check.json' -Wait
Get-Content '.\desktop-check.json'
```

悬浮图标、问答窗口图标和 EXE 图标使用[知乎刘看山官方小站](https://liukanshan.zhihu.com/)提供的角色图片，来源与调整说明见 [图标出处](src/zhijing/assets/ATTRIBUTION.md)。

工作台在每次运行能力前读取当前模型模式。启用 API 时，相关原文、证据与问题会发送到所配置的模型服务。切换资料会清空上一份资料的结果与卡片导出状态，避免导出混用。

修改代码后需要重启服务才能加载新页面路由；重启会丢失页面输入的临时模型配置，需要重新填写。运行中的服务不会自动热重载。

工作台联调命令（需要 PATH 中有 Node.js；应用本身不依赖 Node）：

```powershell
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\scripts\workspace_smoke.py'
```

该命令使用独立测试数据库和临时本地 HTTP 服务，调用真实页面脚本的交互处理函数，验证导入、五项能力、下载、错误和分页；结束后关闭测试服务。它不访问用户资料库，也不调用真实模型。当前无可用浏览器控制环境，视觉与真实浏览器交互验收仍待完成。

## 网页配置模型

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

测试数量、结果和原始证据以最新运行输出为准；根目录历史报告保留了此前快照。自动化中的固定模型响应验证适配器及业务契约，不代表真实 LLM 效果。已有模型 API 的实际五项验证使用 `scripts/ollama_smoke.py --live`，完整命令见 [接入说明](Ollama接入说明.md)。知乎搜索的本地模拟回归与真实调用范围见 [接入与测试](docs/zhihu-search.md)；Anki 桌面导入仍需单独验证。

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
