# Git 同步脚本检查报告

检查日期：2026-09-06。目标仓库：<https://github.com/Kozmosa/zhihu-agent>。

`scripts/sync_github.ps1` 共 123 行，Windows PowerShell 5.1.26100.9168 语法解析错误为 **0**；**12 个本地模拟场景全部通过**。本报告验证脚本的控制流程，不代表 GitHub 登录、真实历史合并或云端推送已经成功。

## 使用方法

可从任意工作目录运行。脚本根据自身位置定位项目，不修改全局 Git 配置；每次 Git 调用仅为此项目设置 `safe.directory`。

```powershell
# 检查工作区、远端地址和默认分支，拉取默认分支信息，输出计划。
powershell -NoProfile -File "E:\CzCode\ZhiJing Agent\scripts\sync_github.ps1"

# 执行合并、普通推送，并核对远端提交 SHA。
powershell -NoProfile -File "E:\CzCode\ZhiJing Agent\scripts\sync_github.ps1" -Publish
```

运行前应提交需要同步的文件，保持工作区干净，并让当前终端中的 Git 能访问目标仓库。预览模式会更新远端跟踪引用，不合并、不推送；现有远端沿用实际默认分支，空仓库使用 `main`。脚本不保存凭据，不执行 `reset`、`clean`、`stash` 或强制推送。

## 关键测试案例

每个案例在独立的 PowerShell 子进程中，用本地 `git` 函数模拟 Git 返回值，记录所有调用。所有 Git 调用均被模拟函数截获，没有执行真实 Git 命令，没有联网，也没有改变真实仓库配置、提交或引用。

| 案例 | 模拟输入 | 预期结果 | 实际结果 |
| --- | --- | --- | --- |
| 预览 | 默认分支为 `trunk`；不传 `-Publish` | 拉取信息；不合并、不推送 | 退出码 0；fetch 1 次；merge / push 均 0 次；通过 |
| 空仓库发布 | 无远端引用；传 `-Publish` | 不合并；普通推送到 `main`；核对 SHA | 退出码 0；push 为 `HEAD:refs/heads/main`；核对通过 |
| 独立历史合并 | `merge-base` 返回 1 | 合并显式携带 `--allow-unrelated-histories` | 退出码 0；仅在该案例加入此参数；随后推送并核对通过 |
| 合并冲突 | merge 返回 1 并报告冲突 | 停止，不推送、不清理冲突现场 | 退出码 1；merge 1 次；push 0 次；无清理调用；通过 |
| 推送失败 | push 返回 1 | 返回失败，不输出成功核验信息 | 退出码 1；push 1 次；未输出 `Verified`；通过 |
| 远端地址不符 | origin 指向其他仓库 | 在拉取或发布前拒绝 | 退出码 1；fetch / merge / push 均 0 次；通过 |

补充 6 个场景也全部通过：有共同祖先时正常合并且保留 `trunk` 目标分支；工作区有改动时拒绝；非空远端无法确定默认分支时拒绝；fetch 失败时停止；推送后 SHA 不一致时报告失败；远端认证失败时停止。每个案例同时检查未调用 `reset`、`clean`、`stash`、`config` 或 `--force`。

## 证据与边界

- 本地测试入口：`E:\CzCode\codex\qa\git-sync-helper\run_mock_tests.ps1`。
- 本轮证据目录：`E:\CzCode\codex\qa\git-sync-helper\run-20260906-160721-523`；含 `results.json`、各案例调用日志和输出。这些临时 QA 文件位于项目外，不属于仓库交付内容。
- 语法检查使用 PowerShell 自带 `System.Management.Automation.Language.Parser.ParseFile`。
- 模拟测试无法验证真实凭据、GitHub 权限、分支保护、网络连接、Git 钩子或实际文件冲突。真实执行仍以 Git 返回值及远端 SHA 核对为准。
- 合并失败后脚本保留 Git 当前状态，需先检查 `git status` 并解决冲突；推送失败也保留已经完成的本地合并。脚本不会自动撤销用户文件或提交。
