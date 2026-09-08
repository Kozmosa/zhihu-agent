# ZhiJing 资料库后端基线

基线编号：`storage-B0-20260908`。建立日期：2026-09-08。结论：资料库事务、分页、搜索可以交接；五项独立能力的离线和模拟模型契约通过，真实模型质量仍待验收。本文件与同目录计划供两条开发线共同使用。

## 基线的确切范围

本基线由 Git 提交 `5d5104a8f4e12406755195f428b5a1dc5e955324` 加上以下六个已验收文件构成。测试在独立快照中运行，避免共享 checkout 的并发更新改变验收对象。

| 文件 | 本次范围 |
| --- | --- |
| `src/zhijing/infrastructure/sqlite_sources.py` | 批量原子事务、数据库分页、搜索快照、锁冲突错误 |
| `src/zhijing/features/sources/service.py` | 服务层调用 |
| `src/zhijing/features/sources/router.py` | 搜索接口和 offset 范围 |
| `src/zhijing/domain/models.py` | 新增 `SourcePage` |
| `src/zhijing/domain/ports.py` | 扩展 `SourceRepository` |
| `tests/test_source_storage.py` | 24 项资料库回归测试 |

六个文件均与上一轮已验收 SHA256 一致。本轮没有再次修改应用代码，也没有切换分支、提交或推送。当前分支仍是 `feat/knowledge-workspace-ui`。基线编号是本地验收记录，不是 Git tag 或已发布版本。

共享目录正在更新的 reader、batching、模型适配、配置、装配入口及 web 等内容没有合入 B0。不要将本记录的 210 项通过套用到整个持续变化的 checkout。完整后端工作流和长文能力需要各自完成验收再形成后续基线。

快照：`E:\CzCode\codex\qa\zhijing-storage-baseline-20260908-161046\snapshot`。

项目内证据：[manifest.json](evidence/storage-B0-20260908/manifest.json)、[pytest.log](evidence/storage-B0-20260908/pytest.log)、[pytest.xml](evidence/storage-B0-20260908/pytest.xml)、[ollama-mock.json](evidence/storage-B0-20260908/ollama-mock.json)。manifest 记录提交、覆盖文件和快照各文件的 SHA256。

可还原的六文件增量：[storage.patch](evidence/storage-B0-20260908/storage.patch)。它应用于上述基准提交，可还原资料库 B0；已在 B0 快照执行 `git apply --reverse --check` 验证补丁一致性。仅在另建的干净检出目录应用，不能对正在协作的当前 checkout 重复应用。测试后重新校验 manifest，各被测文件哈希未变。

## 本轮验收

| 检查 | 结果 |
| --- | --- |
| 独立快照全量 pytest | 210 项通过，2 个已有依赖弃用警告，10.37 秒 |
| Ruff lint 与格式 | `src/zhijing tests scripts main.py` 通过，99 个 Python 文件格式合格 |
| 正式入口 `main.py --check` | `ready=true`；仅导入和配置自检 |
| 正式入口 Ollama 模拟 HTTP | 五项能力 5/5 通过；使用隔离数据库和固定响应 |
| 内部只读资料库复核 | 未发现必须修改的问题；此审查不是用户另一个终端的确认 |

本次没有真实模型调用。上一轮资料库真实 HTTP 与重启验证已通过，证据位于 `E:\CzCode\codex\qa\zhijing-backend-20260908\source-http.json`；该证据保留其原验证范围，不替代本轮快照测试。

解释器：`E:\CzCode\codex\envs\zhijing\Scripts\python.exe`，Python 3.12.7。FastAPI 0.141.1、Pydantic 2.13.5、Uvicorn 0.52.4、httpx 0.28.1、genanki 0.13.1。未安装或升级依赖。所有写入测试使用隔离数据库；业务库未参与。

## 资料库接口契约已实现

- `POST /api/v1/sources/import`：请求 `{"items": [...]}`，每次 1 至 20 条；成功返回原有 Source 数组。整批提交或整批回滚，保留已有记录。重复资料保持相同 ID 和首次创建时间。
- `GET /api/v1/sources`：继续返回数组；可传 `author_id`、`offset`、`limit`。默认 offset=0、limit=20，limit 范围 1 至 100。
- `GET /api/v1/sources/search`：返回 `{items,total,offset,limit,has_more}`。参数同上，增加可选 `q`，最多 200 字符。
- `GET /api/v1/sources/{source_id}`：原资料详情接口不变。

搜索 q 去除两端空白，匹配标题、作者名称、原文、主题中的字面子串；ASCII 英文不区分大小写。`%`、`_`、引号、反斜杠不作为 SQL 通配符。空 q 返回全部匹配作者范围内的资料。author_id 是精确筛选。结果按 ID 排序。

offset 范围为 0 至 9223372036854775807，越界 HTTP 422。SQLite 等待锁超时后返回 HTTP 503 和 `storage_busy`。未找到单条资料返回 HTTP 404 和 `source_not_found`。旧 v1 数据库无需迁移或重新导入。

已知限制：搜索扫描 JSON 字段；没有全文索引或语义检索。单次响应中的 count 与 items 使用同一事务快照，不同翻页请求之间的新增资料可能移动页边界。业务检索、图谱和审查仍有全量语料读取，不属于本次分页优化范围。

## 后续开发前必须区分的状态

| 功能 | B0 状态 |
| --- | --- |
| 五项独立能力 | 离线与模拟模型契约通过 |
| 任意真实模型的效果 | 未验收，不能由接口兼容推导 |
| companion 五项统一工作流 | B0 仅组合 reading/cards/facts/author，尚缺 knowledge |
| 任务进度、历史与结果持久化 | 尚未实现 |
| 中途失败保留和复用已完成步骤 | 尚未实现 |
| 长文分批 | B0 尚未实现；共享目录中已出现进行中的实现，须单独验收 |
| 知乎采集与同步 | 尚未实现；origin=zhihu 和 URL 不等于已经采集 |
| 悬浮球或桌面伴侣 | 本轮不制作前端；先确定运行与来源接口 |

## 复验命令

以下命令针对固定 B0 快照；验证当前开发线时另用其快照和新报告，不能覆盖此份证据。

```powershell
$testPython = 'E:\CzCode\codex\envs\zhijing\Scripts\python.exe'
$snapshot = 'E:\CzCode\codex\qa\zhijing-storage-baseline-20260908-161046\snapshot'
$qaRun = Join-Path 'E:\CzCode\codex\qa' ('zhijing-B0-recheck-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
Set-Location -LiteralPath $snapshot
& $testPython -m pytest -q -p no:cacheprovider --basetemp "$qaRun\pytest" --junitxml "$qaRun\pytest.xml"
& $testPython -m ruff check --no-cache src/zhijing tests scripts main.py
& $testPython -m ruff format --check --no-cache src/zhijing tests scripts main.py
& $testPython main.py --check
& $testPython scripts/ollama_smoke.py --mock --work-root "$qaRun\mock" --report "$qaRun\ollama-mock.json"
```

工作分配与未来接口见 [NEXT_CONTRACT.md](NEXT_CONTRACT.md)。唯一协作回执写入 [CLI_HANDOFF.md](../../src/_review/20260908/CLI_HANDOFF.md)。
