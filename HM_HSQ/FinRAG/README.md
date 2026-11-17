# 通用文档 RAG

## 统一启动

在本项目文件夹双击 `start.bat`，或在 PowerShell 中执行 `./start.ps1`。统一入口会检查 Docker、启动 `finrag-milvus`、启动 FastAPI 和 Vue 前端，然后打开 http://127.0.0.1:5173 。已运行的服务会被复用。

本机已经完成依赖安装、Milvus 容器创建和模型密钥配置。启动脚本沿用 `EduRAG_GANG` 环境，其他机器可通过 `RAG_PYTHON` 指定已安装依赖的 Python 可执行文件。服务日志保存在 `.runtime` 目录。

仅启动服务并跳过打开浏览器时，执行 `./start.ps1 -NoBrowser`。下文的独立启动命令用于分别运行各服务。

## 结构与整改

原项目入口将 FAQ 检索、数据库会话记录、课程业务提示词和学科分类器耦合。命令行入口为 `new_main.py`，HTTP 服务入口为 `run_api.py`。

- `base/config.py` 读取运行参数与领域配置。
- `rag_qa/core/document_processor.py` 解析本地文件并进行父子分块。
- `rag_qa/core/vector_store.py` 使用 BGE-M3 稠密与稀疏混合检索、父块聚合和 BGE 重排序。
- `rag_qa/core/rag_system.py` 构造领域提示词、生成流式回答并列出文件及页码来源。
- 每个 `knowledge_base` 映射到独立 Milvus 集合。导入与提问必须使用相同的标识。
- 会话历史保存在应用实例内存中，每个会话保留最近五轮，进程退出后释放。

FAQ、Redis、MySQL 的代码已移除。旧业务文档、分类训练资源及旧加载器迁移至项目同级的 `FinRAG_legacy_backup`，便于恢复。项目根目录的 `金融.pdf` 可直接导入。

## 环境

建议 Python 3.10 或 3.11，在独立虚拟环境安装依赖。

```powershell
python -m pip install -r requirements.txt
$env:RAG_API_KEY = '你的模型服务密钥'
```

需要可访问的 Milvus 服务，默认 `localhost:19530`，数据库为 `default`。模型路径默认指向现有 `rag_qa/models/bge-m3` 与 `bge-reranker-large`，相对路径以配置文件目录为基准。设备自动选择 CPU 或 CUDA 用于重排序，嵌入默认使用 CPU。

## 使用

```powershell
python new_main.py --knowledge-base finance --domain 金融 ingest .\金融.pdf
python new_main.py --knowledge-base finance --domain 金融 ask "请概括文档的主要内容"
python new_main.py --knowledge-base finance --domain 金融 chat
python new_main.py --knowledge-base legal --domain 法律 ingest .\法律资料
python new_main.py --knowledge-base legal --domain 法律 chat
```

`ingest` 接收单文件或递归目录。支持 PDF、TXT、Markdown、DOCX、PPTX、PNG、JPG、JPEG。扫描 PDF 的无文本页面及图片使用 OCR。Word 提取段落和表格，PPTX 提取文本框。文本文件使用 UTF-8。PDF 页码与 PPT 页码对应原文件，其他文件按单个逻辑页面标记。

`config.ini` 中的 `domain` 和 `instructions` 可设置领域名称与补充要求。`--config` 可选择独立配置文件。领域名称用于生成提示词，`knowledge_base` 决定知识库隔离。不同业务应指定不同知识库标识。

相同路径、相同内容重复导入通过稳定 ID 去重。导入采用分批 upsert，失败后可以重新执行。导入属于增量追加，文件修改后的旧块仍保留，需要使用新的知识库标识重新构建完整文档版本。

`IntegratedQASystem` 可注入向量存储与模型调用函数。`query` 保持 `(文本片段, 是否结束)` 的流式接口。`source_filter` 如需使用，应传入导入时的文件绝对路径。

当前检索返回排名靠前的候选资料，资料充分性由生成提示词约束，尚未设置经过领域评测的相关性拒答阈值。

## 本次验证

`金融.pdf` 已实测提取 92 页、184 个子块。已检查重复处理标识稳定、子块长度、命令行入口、应用导入链路、知识库集合命名隔离、流式协议、来源输出和内存会话隔离。

应用层测试和真实 Milvus、BGE 模型检索、远端 LLM 生成均已验证。

本次在当前用户 Python 3.12 环境安装了文档解析所需的 LangChain core、text splitters 和 PyMuPDF。pip 报告了该环境已有软件包之间的依赖冲突，完整运行环境仍需按依赖文件在独立虚拟环境中准备。

## 本机运行验证

已使用本机 `EduRAG_GANG` Conda 环境启动 Milvus 2.5.2，Docker 容器名为 `finrag-milvus`，数据卷名为 `finrag-milvus-data`。服务端口绑定在本机 `127.0.0.1:19530`。

`finance` 知识库已成功导入 `金融.pdf` 的 184 个文档块，真实 BGE 混合检索与重排序已返回 3 个参考父块。模型服务密钥从配置读取，完整问答已验证并输出文件与页码引用。

本机启动脚本 `run_project.ps1` 指向现有 `EduRAG_GANG` Python 路径，并优先加载该环境的依赖，使用 UTF-8 输出。

```powershell
$env:RAG_API_KEY = '你的模型服务密钥'
.\run_project.ps1 --knowledge-base finance --domain 金融 chat
```

后续重启 Milvus 可执行 `docker start finrag-milvus`。

## FastAPI 与 Vue 前后端

前端使用官方 RuoYi-Vue3 模板的样式与组件，采用 Vue 3、Vue Router、Element Plus 和 Vite。模板来源为 https://github.com/yangzongzhuan/RuoYi-Vue3 ，保留前端目录中的 MIT 许可。已配置知识库管理和文档问答页面。

后端启动命令在项目根目录执行。

```powershell
.\run_api.ps1
```

前端启动命令在另一个终端执行。

```powershell
cd frontend
npm ci
npm run dev
```

页面地址为 http://127.0.0.1:5173 ，FastAPI 地址为 http://127.0.0.1:8010 ，Swagger 文档地址为 http://127.0.0.1:8010/docs 。Vite 将 `/api` 请求代理到 FastAPI。前端生产构建执行 `npm run build`，输出到 `frontend/dist`。正式部署时需要将 `/api` 转发至 FastAPI，并为 Vue Router 配置 history 路由回退。

`run_api.ps1` 使用本机现有 Conda 环境。其他机器可在安装 requirements.txt 后执行 `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8010 --workers 1`。

知识库名称、领域、补充要求和上传文档清单保存在 `.runtime/web/knowledge_bases.json`，上传原文件保存在 `.runtime/web/uploads/<知识库标识>`。向量仍存储在 Milvus。模型在第一次导入或问答时加载，多知识库共用模型。单个进程按顺序处理推理与入库，避免共享模型并发冲突。正在推理期间其他知识库管理请求可能需要等待。

接口支持知识库列表与创建、文档列表与上传、SSE 流式问答和会话清空。上传上限为 50 MB，相同文件内容重复上传保持幂等。CLI 导入和网页文档清单分别管理，已有金融文档清单已迁移。后续使用 CLI 导入的文件需要另行同步网页清单。

当前为本机单用户工作台，若依的登录、用户角色和权限管理尚未接入。会话记录保存在服务内存，服务重启后释放，页面刷新会开始新会话。模型密钥仅由后端读取。

浏览器工具连接状态异常，因此本次可视化验收尚未完成。前端构建、后端真实生成和前端代理通过接口联调验证。



## 冗余文件清理

已移出重复启动入口、未接入当前页面的若依系统管理/监控/代码生成模块、配套接口与工具、旧构建脚本、模板示例资源和验收临时文件。可恢复备份位于项目同级 `FinRAG_unused_backup`。当前运行入口为 `new_main.py`（命令行）、`run_api.py`（FastAPI），两个 PowerShell 启动脚本负责选择本机 Python 环境。前端入口为 `frontend/src/main.js`，由 Vite 构建。

