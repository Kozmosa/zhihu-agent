# 知境 ZhiJing Agent

v0.2 已为长文拆解、答主问答、记忆卡片、事实审查、知识地图接好统一的 Ollama 生成适配器。默认仍是可离线运行的规则与摘录模式；配置已有的 Ollama 原生 API、模型名称和可选鉴权后，重启服务即可让五项能力调用模型。真实效果取决于模型输出质量，接通接口不等于完成效果评估。

项目正式入口是根目录的 **Start.cmd**，双击即可启动本地 Server，并在服务就绪后打开 API 文档。保留服务终端运行，按 Ctrl+C 停止。

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

默认地址为 `http://127.0.0.1:8000/docs`。双击启动时解释器依次选择项目 `.venv`、`E:\CzCode\codex\envs\zhijing`、PATH 中的 Python；启动前检查依赖。

```powershell
# 在任意目录执行环境自检，不创建数据库或启动服务
& 'E:\CzCode\ZhiJing Agent\Start.cmd' --check

# 在任意目录指定端口启动
& 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe' 'E:\CzCode\ZhiJing Agent\main.py' --port 8001
```

使用已安装依赖的解释器，也可在项目目录直接执行 `python main.py`。加 `--open-browser` 会在健康检查通过后打开浏览器。若端口被占用，选择其他端口，不会自动关闭已有服务。

首次使用请在 `POST /api/v1/sources/import` 导入 [examples/sources.json](examples/sources.json)，用响应中的 `source_id` 测试各接口；示例不会随启动自动写入数据库。也可运行 `scripts/demo.py`，它会导入同一组示例并调用统一工作流。

## 接入已有模型 API

在同一个 PowerShell 终端设置环境变量后启动，已有服务需先停止再重启：

```powershell
$env:ZHIJING_MODEL_PROVIDER = 'ollama'
$env:ZHIJING_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZHIJING_OLLAMA_MODEL = '替换为服务端可用的模型名'
& 'E:\CzCode\ZhiJing Agent\Start.cmd'
```

地址填写服务基地址，允许末尾 `/api` 和代理前缀，不填写完整 `/api/generate` 或 `/api/chat`。适配器调用 Ollama 原生 `/api/generate`，不能直接使用任意 OpenAI `/v1` API。`.env.example` 仅作参考，`.env` 不会自动加载。格式模式、可选密钥和上下文预算见 [接入说明](Ollama接入说明.md)。

五项结果通过 `mode` 区分 `extractive` 与 `ollama`。没有可用证据时，问答、审查和地图会直接返回不足或空结果；模型错误会明确失败，不会静默切回规则。事实审查只解释当前证据与主张的关系，引用存在不等于判断正确或事实为真。

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
