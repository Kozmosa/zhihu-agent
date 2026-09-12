# 知乎搜索接入与测试

知识工作台通过知乎官方搜索 API 获取回答、文章等搜索摘要。用户先预览，再选择导入本地资料库；填写普通来源链接仍只保存链接，不触发网页抓取。

## 网页使用

1. 启动 `Start.cmd`，进入 `/workspace`，点击左侧“搜索知乎”。
2. 登录[知乎开放平台](https://developer.zhihu.com/)，在个人中心获取 Access Secret；在搜索面板的配置区域填写并启用。
3. 输入关键词，选择 1～10 条结果并搜索。点击搜索会使用账号额度，不会自动翻页或重试。
4. 核对标题、作者、摘要和来源链接，点击“导入摘要”。导入后该资料会被选中，可用于阅读、问答、卡片等现有功能；这些功能分析的是已导入摘要。

网页配置只保存在当前服务进程内存，成功后清空密码框；不写 `.env`、数据库或浏览器存储，接口只返回是否配置。重启后需要重新填写。也可通过启动环境变量 `ZHIHU_ACCESS_SECRET` 配置；可选 `ZHIHU_SEARCH_TIMEOUT` 默认为 20 秒。`.env.example` 是参考文件，程序不会自动加载 `.env`。

知乎搜索独立于模型配置：离线摘录模式也可以主动搜索知乎。切换模型配置不会清除知乎配置。点击“清除会话凭证”可清除服务中的知乎密钥；关闭网页不会自动清除服务凭证。页面使用现有的本机地址、Origin 和会话令牌校验。

## 内容范围与兼容性

- 官方 `ContentText` 是摘要，可能带 `<em>` 高亮标签；后端转换为纯文本，前端按文本展示，避免运行远程 HTML。缺少可导入内容或格式无效的结果会跳过并提示数量。
- 导入保存 `content_extent=excerpt`，同时保存来源内容 ID、内容类型、原始溯源链接、规范链接、获取时间和文本哈希。资料库、当前资料和搜索预览都会标明摘要。
- 接口不提供稳定作者 ID。为避免同名作者混合，使用每条内容独立的本地范围 ID，真实 `external_author_id` 保持空值；按作者问答不会把相同昵称自动归为同一作者。
- 接口的 `ContentID` 按不透明字符串保存，支持负号开头的 ID；它不一定等于来源 URL 中的数字，不将其转换为正整数或据此拼接 URL。
- 同一条摘要再次搜索后导入，即使获取时间或链接 UTM 参数变化也不会新增记录；内容改变则保存新版本。
- 历史资料无需迁移或重新导入，新增字段缺省为 `content_extent=unknown`，显示“已导入内容”，不推断历史资料是完整正文。原有普通导入记录的 ID 和去重规则保持兼容。

## API 与失败处理

本地新增路由均要求从本机调用；POST 还需要当前页面的 `X-Zhijing-Token`：

| 路由 | 请求与响应 |
| --- | --- |
| `GET /api/v1/zhihu/status` | 返回 `configured`，不返回凭证 |
| `POST /api/v1/zhihu/config` | 请求 `{"access_secret":"..."}`；只更新服务会话，不发起外部请求 |
| `POST /api/v1/zhihu/search` | 请求 `{"query":"学习方法","count":3}`；返回 `items`、`has_more`、`empty_reason`、`skipped_count` |
| `POST /api/v1/sources/import` | 使用既有导入接口，将选中的搜索项放入 `items` 数组保存 |

外部请求固定发往 `https://developer.zhihu.com/api/v1/content/zhihu_search`，使用 GET、Bearer 认证、秒级 `X-Request-Timestamp`、`Query` 和 `Count`。不使用浏览器 Cookie，也不请求结果页来尝试取得全文。

只有 HTTP 成功、JSON 业务 `Code=0` 且结果结构有效时，才视为成功。缺少密钥、鉴权失败、频率限制、超时、网络错误和异常响应分别报告；不会将 HTTP 200 的业务失败当作成功。错误响应不回显密钥或未经筛选的上游错误文本。

当前官方 API 无分页参数，`HasMore` 固定为 false。额度可在平台个人中心的用量统计查看；具体额度取决于账号。

协议依据：[搜索 API](https://developer.zhihu.com/docs?key=zhihu_search)、[搜索 Skill](https://developer.zhihu.com/docs?key=zhihu_search_skill)、[鉴权](https://developer.zhihu.com/docs?key=authorization)、[额度查询](https://developer.zhihu.com/docs?key=quota)。

## 验证

在项目环境中执行：

```powershell
python -m pytest -q
python scripts/workspace_smoke.py --work-root work/workspace-smoke
```

pytest 的知乎用例使用假密钥和模拟 HTTP 响应，验证鉴权、参数、业务错误、超时、数据清洗、摘要来源、配置隔离和去重。工作台验收使用隔离资料库和模拟搜索响应验证页面事件及真实本地导入，不消耗知乎搜索额度。页面真实搜索需使用自己的凭证和额度，不能将模拟测试当作真实数据获取成功。
