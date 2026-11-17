# AICrawl Enterprise 最小可运行原型

已完成第一轮企业化工程改进：固定线程池、队列容量、幂等提交、分页 API、请求追踪、轮转日志、运行配置和优雅关闭。详见 [企业级改进说明](企业级改进说明.md)。当前仍为无需数据库的本机原型。

根据上级目录 `../项目设计方案` 中的 PRD、SDD、整体流程图及可行性研究报告，实现本地业务闭环。无需数据库、Redis、Docker、Node.js 或 API Key，无第三方 Python 依赖。

## 启动

安装 Python 3.10 或更高版本，进入 `AICrawl_Enterprise_V1.0` 目录后执行：

```powershell
python run.py
```

浏览器访问 **http://127.0.0.1:8000**。Windows 也可双击 `start.bat`。终端按 Ctrl+C 停止。

端口被占用时：`python run.py --port 8001`，然后访问对应端口。

## 体验流程

1. 在“采集任务”选择一个预置任务，点击“立即运行”。
2. 在“运行批次”查看进度、日志，体验暂停、恢复、取消。
3. 在“数据资产”查看 2 条已发布记录及 1 条异常记录，打开详情查看原始 JSON、证据定位、SHA-256、来源及批次。
4. 在“质量复核”填写理由并驳回异常记录。硬性校验失败不能人工直接放行。
5. 在“数据资产”下载已发布记录的 CSV（UTF-8 BOM，可由 Excel 打开）。
6. 也可新建数据源 → 审批启用 → 创建任务 → 运行。新建来源选择内置样本类型，不填写真实网站地址。

相同来源重复运行会按内容去重，新批次新增记录可以为 0。每类样本固定包含两条合格、一条异常记录，数据均为虚构。重启会清空所有操作与结果，恢复初始来源和任务。

## 结构与取舍

```text
backend/service.py    领域服务、内存仓库、状态机、后台线程、质量门禁与审计
backend/server.py     JSON HTTP API、CSV 导出、前端静态资源
frontend/             管理界面（HTML / CSS / JavaScript）
tests/test_system.py  真实 HTTP 集成测试
run.py                单进程启动入口
start.bat             Windows 启动入口
```

用户要求先做最小原型，因此暂用标准库 HTTP 服务和原生前端代替目标方案中的 FastAPI / React，领域逻辑与 HTTP 层已分离。前端通过 `/api/v1` 调用后端，每 1.5 秒同步状态；后台工作线程执行本地样本读取、结构化、质量检查与发布。没有运行时外网依赖。

## 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查及运行模式 |
| GET | `/api/v1/state` | 本地控制台全量状态 |
| POST | `/api/v1/sources` | 创建来源，`name/kind` |
| POST | `/api/v1/sources/{id}/{approve,suspend,resume}` | 来源审批、停用、恢复 |
| POST | `/api/v1/jobs` | 创建任务，`name/source_id` |
| POST | `/api/v1/jobs/{id}/runs` | 启动批次 |
| POST | `/api/v1/runs/{id}/{pause,resume,cancel}` | 批次控制 |
| POST | `/api/v1/records/{id}/review` | 复核，`decision/note` |
| GET | `/api/v1/export.csv` | 导出已发布数据 |

POST 使用 JSON，对无参数操作也发送 `{}`。类型 `kind` 为 `jobs/products/notices`。错误为 `{"error":{"message":"原因"}}`。

## 验证

```powershell
python -m unittest discover -s tests -v
node --check frontend/app.js
```

集成测试覆盖来源准入、状态控制、重复执行限制、异常隔离、阻止违规发布、复核、去重、取消不发布、CSV、静态页面及非法请求。

## 本期边界与后续设计

- 当前仅支持本地 JSON 样本，执行日志明确标注样本阶段。尚未实现真实 HTTP / 浏览器 / PDF 抓取、CSS/XPath 模板编辑、AI 抽取、定时调度、代理与告警。
- 单用户演示管理员，无登录、OIDC、RBAC 或多租户；源审批为演示状态迁移。仅监听 `127.0.0.1`，用于本机原型体验。
- 记录含原始 JSON 证据及 SHA-256，规则分数仅表示样本字段完整性，不是准确率。复核不改写证据；修复编辑与版本回放留待下一轮。
- 内存去重按 `source_id + payload hash`，未实现生产自然主键和历史版本。审计同样为内存列表，不具备生产防篡改能力。
- 下一步先将 HTTP 层迁移为 FastAPI、前端迁移 React + TypeScript，再以 Repository 接口替换内存仓库，引入 PostgreSQL / Outbox 和 Redis / Celery；随后接入获准真实来源适配器及独立证据存储。生产方案仍以设计文档的权限、网络、安全、可靠性要求为准。
