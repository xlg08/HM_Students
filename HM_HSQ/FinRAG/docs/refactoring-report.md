# 重构报告

## 现状分析与能力清单

本次以已运行的 FinRAG 为基线，在原代码中迭代。工作目录的实际工程位于 `HM_Students/HM_HSQ/FinRAG`。检查时该目录没有 Git 仓库，无法通过 Git 状态区分历史改动。本次保留用户 `config.ini`、原始 PDF、已有 Milvus 集合、上传数据、启动入口和 Vue 项目，未执行提交操作。

| 能力 | 重构前现状 | 本次处理 |
| --- | --- | --- |
| 文档加载、PDF、DOCX、PPTX、图片 OCR | 已有 | 复用并扩展类型分发 |
| 文本清洗 | 缺少独立步骤 | 增加空字符和空白规范化 |
| 父子分块 | 已有 | 保留并添加稳定 Chunk ID |
| BGE-M3 Embedding、Milvus、混合检索、BGE 重排 | 已有 | 保留实现，增加异常处理和集合提交清单 |
| Collection 隔离 | 已有基于标识哈希的独立集合 | 增加真实数据隔离测试 |
| Prompt 和 LLM | 已有 | 保留通用模板与函数注入 |
| 上下文预算 | 缺失 | 独立 Context Builder，UTF-8 字节预算保守限制 |
| 结构化来源 | 缺失，只有文本来源 | 增加同步 JSON 问答契约 |
| 文档更新和回退 | 更新后旧块会混入检索 | 使用有效 ID 清单原子提交，保存上一版清单 |
| 独立领域配置 | 默认配置加名称/要求 | 增加 Collection INI 叠加与环境覆盖 |
| 自动化测试 | 未形成可复用测试文件 | 增加 unittest 单元和真实 Milvus 集成测试 |

Python 运行环境为本机 Conda Python 3.10，兼容项目建议 Python 3.10/3.11。Web 使用 FastAPI、Uvicorn，文档和切分使用 LangChain Core / Text Splitters，LLM 为 OpenAI 兼容 DashScope，嵌入为 BGE-M3，向量库为 Milvus 2.5.2。前端为 Vue 3 / RuoYi-Vue3 / Element Plus / Vite。Office 表格使用 openpyxl、xlrd，旧 DOC 使用 LibreOffice 或 Windows Word COM。

## 原始调用链与耦合位置

最初项目的集成入口直接初始化 MySQL、Redis 和 FAQ/BM25 查询，再回退到 RAG。MySQL 同时承担 FAQ 数据和对话历史，Redis 承担 FAQ 缓存。原文档处理根据目录名推断学科，Prompt 包含培训课程与客服电话，查询分类器通过本机绝对路径加载业务分类模型。

上述旧模块在先前整改中已移出运行工程。本次基线仍存在的业务耦合是 API 首次启动默认创建金融知识库，现已改为读取默认配置。保留的金融和法律条目是用户已有外部运行数据，示例领域配置位于 `configs/collections/*.example.ini`。

当前调用链为 CLI / API → IntegratedQASystem → Document Processor 或 RAGSystem → VectorStore / Retriever → BGE-M3 与 Milvus → Context Builder → Prompt → LLM。RAGSystem 使用 Retriever 结构接口和注入的模型函数，核心没有业务分支或领域 Service 映射。

## 模块分类和依赖影响

| 模块类别 | 结果 |
| --- | --- |
| 通用核心 | 保留 document_processor、vector_store、rag_system、prompts，增加 file_parsers、context_builder、interfaces |
| 可泛化能力 | API 领域默认值改为配置，模型实例按路径组合共享 |
| 业务专属 | 原教育分类器、课程数据和专属提示词已移出当前工程 |
| FAQ 缓存 | 当前源码、配置、依赖和启动链路不存在读取写入功能 |
| Redis | 原 FAQ 调用链已移除，当前没有直接或间接客户端依赖 |
| MySQL | 原 FAQ 与会话依赖已移除，当前没有 SQL 连接和 ORM 初始化 |
| 最小替代 | 对话使用内存，知识库和上传映射使用 JSON，文档来源与有效索引用 Milvus 元数据及本地 JSON |

应保留用户资料、模型、向量、来源、知识库配置。原 FAQ 数据和缓存不属于当前 RAG 必需数据，旧代码位于工程外的可恢复备份。核心切分、向量、父块映射和来源能力均保留。向量映射自始使用 Milvus 元数据，本次无需迁移 MySQL 向量映射。

## 关键修改文件

- `base/config.py` 增加独立配置叠加、标识和预算校验、环境覆盖。
- `rag_qa/core/document_processor.py` 增加清洗、来源元数据、内容哈希和 Chunk ID。
- `rag_qa/core/file_parsers.py` 增加 DOC、Excel、XMind、FreeMind、OPML。
- `rag_qa/core/vector_store.py` 增加文件锁、版本提交清单、旧索引基线、逻辑删除、历史回退、模型一致性检查和重排异常降级。
- `rag_qa/core/context_builder.py`、`interfaces.py` 提供实际使用的预算与检索契约。
- `rag_qa/core/rag_system.py` 增加 JSON 结果、结构化来源和告警，保留流式接口。
- `new_main.py` 保留原入口，增加 `--collection` 别名、查询不存在集合时出错及文档索引删除。
- `backend/app.py` 移除业务默认值，新增 v1 上传和查询、文档删除接口，同名上传切换当前版本，兼容已有索引来源路径。
- `frontend/src/views/rag/Workspace.vue` 更新上传格式列表。
- `requirements.txt` 增加 openpyxl、xlrd、filelock，没有新增传统业务数据库和任务队列。
- `.gitignore`、`.env.example`、`config.example.ini` 避免新提交包含真实密钥、模型或私有资料。

## 更新策略与兼容性

原 Milvus schema 通过动态元数据扩展，现有集合可读。首次变更先扫描原集合创建有效 ID 基线，再写新块并切换清单。写入失败时保持旧清单，新版本的未提交块不参与检索。旧物理向量保留，查询由清单过滤。

需要回退时先停止所有访问该集合的进程，将 `.previous.json` 恢复为同名 `.json`，再启动。首次建立基线没有上一版清单，原向量库保持原状。清单与向量库需共同备份。当前采用文件系统锁及原子重命名，面向同一机器上的本地文件系统。大型分布式部署不在本次范围内。

原 CLI、网页 SSE 接口及默认服务端口保持可用。新增同步接口在 `sources` 之外提供 `warnings`。查询不存在的 Collection 现在明确失败，无法继续依靠查询隐式创建 Collection。文档删除是逻辑停用，原文和旧物理向量保留。用户已有 `config.ini` 的密钥读取继续兼容，推荐新部署使用环境变量。

## 实际测试记录

在 `EduRAG_GANG` 环境运行 unittest，使用确定性 Embedding 和重排器对真实 Milvus 验证，测试集合使用随机标识并在结束后清理。

已执行的检查包括单文件 PDF 入库、PDF 与 Markdown 目录批量入库、不存在文件、空文本和空白 PDF、重复 Chunk ID、DOCX、XLSX、旧版/新版 XMind、FreeMind、OPML、DOC 转换不可用错误、上下文预算、结构化来源、空证据不调用 LLM、LLM 错误传播、集合标识验证。

真实 Milvus 测试直接断言三套集合的检索正文和来源，不依靠 LLM 答案判断隔离。覆盖重复入库、替换后只检索当前版本、模拟写入失败后保留旧版本、独立 Python 子进程重新打开集合、逻辑删除后无结果、未知 Collection 报错，以及数值异常重排的显式降级。

另已执行前端 `npm run build`、Python compileall 和真实 BGE / 远端 LLM 的 `/api/v1/rag/query` 联调。接口返回 HTTP 200、真实答案和结构化来源。此次真实模型重排出现非有限分数，响应明确携带降级告警并使用同集合混合检索排序。

全项目搜索 `redis|mysql|pymysql|aiomysql|faq`，运行源代码、配置、依赖和启动脚本没有实际依赖。说明文档中保留历史重构记录。

## 限制与未完成的外部验证

- 本机 Word 自动化创建 DOC 测试文件时阻塞，已终止本次测试创建的 Word 进程。真实 DOC 转换尚未验证，相关入口有超时和失败报错。LibreOffice 当前未检测到，部署旧 DOC 支持需准备转换工具。
- XLS 使用 xlrd 的真实实现，但此次没有真实 XLS 样本。XLSX 已验证。其他专有脑图格式需要先导出为受支持格式。
- 实际生产 PDF、BGE 和模型生成已测，扫描 PDF 的真实 OCR 图片质量尚未重新验证。空页面测试使用 Mock OCR 验证失败处理。
- 本机重排模型会出现 NaN。显式降级保证 RAG 查询仍可用，根本的模型/运行环境数值问题仍需进一步定位。正常有限分数的重排路径继续保留。
- 有效 ID 清单适合当前本地规模。超大集合需评估过滤表达式大小，旧物理版本没有自动 GC。
- CLI 和网页文档列表暂未完全统一，网页新上传与同名替换通过统一索引流程管理。
- 网页仍是本机单用户版本，浏览器自动化连接此前异常，可视化交互验收未重新完成。

最终自动化回归在本机 `EduRAG_GANG` 环境执行，8 个测试全部通过，耗时 90.290 秒。执行时设置 `RAG_INTEGRATION=1`，并将 Conda 环境包路径放在用户级包路径之前。前端生产构建成功，Python compileall 成功。

实际回归命令如下。

```powershell
$env:RAG_INTEGRATION = '1'
& 'E:\ProgrammingLanguage\Python\Anaconda3\Anaconda3-2024\anaconda3\envs\EduRAG_GANG\python.exe' -X utf8 -c "import sys; u=[p for p in sys.path if 'AppData' in p and 'site-packages' in p]; sys.path[:]=[p for p in sys.path if p not in u]+u; import unittest; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests')); sys.exit(not r.wasSuccessful())"
```
