# 通用领域 RAG

本项目在现有 FinRAG 上重构，沿用 BGE-M3、Milvus、BGE 重排序和 OpenAI 兼容模型服务。CLI、FastAPI 和 Vue 3 / RuoYi-Vue3 前端使用同一套文档处理与问答流程。

## 安装和模型配置

建议使用 Python 3.10 或 3.11、Node.js 20 及以上版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.ini config.ini
$env:RAG_API_KEY = '你的模型服务密钥'
cd frontend
npm ci
cd ..
```

`config.example.ini` 中的模型路径对应已有的 `rag_qa/models/bge-m3` 和 `bge-reranker-large`。其他机器需自行准备相同模型文件并配置路径。真实模型生成需要有效密钥和网络连接。现有 `config.ini` 保留兼容，环境变量优先。

Milvus 是必要的向量持久化服务。现有机器的容器名为 `finrag-milvus`，执行 `docker start finrag-milvus` 即可恢复。新机器可使用 Milvus 官方的嵌入式 etcd Docker 安装方式，见 https://milvus.io/docs/v2.5.x/install_standalone-docker.md 。服务默认连接 `localhost:19530`、数据库 `default`。

## 本机统一启动

双击 `start.bat` 或执行 `./start.ps1`。本机脚本默认使用已有的 `EduRAG_GANG` 环境，其他 Python 环境通过 `RAG_PYTHON` 指定。前端为 http://127.0.0.1:5173 ，后端 Swagger 为 http://127.0.0.1:8010/docs 。脚本会复用已运行的服务。

手动启动后端可执行 `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8010 --workers 1`，前端在 `frontend` 目录执行 `npm run dev`。当前是本机单用户版本，登录权限管理尚未接入。

## 文件入库和领域切换

命令中的知识库标识可以任意命名，统一映射到独立的 Milvus 集合。示例命令按本项目已有 CLI 实现。

```powershell
# 金融 PDF，根目录现有文件可直接使用
python new_main.py --collection finance --domain 金融 ingest ./金融.pdf
python new_main.py --collection finance --domain 金融 ask "文档如何规定固定资产入账？"

# 法律 PDF 需要用户自行放入 documents/legal 目录
python new_main.py --collection legal --domain 法律 ingest ./documents/legal/法律.pdf
python new_main.py --collection legal --domain 法律 ask "请概括资料中的主要条款"

# 目录批量导入与第三个领域
python new_main.py --collection research --domain 科研 ingest ./documents/research
python new_main.py --collection research --domain 科研 chat

# 从指定知识库停用一个源文件的索引
python new_main.py --collection research delete-document ./documents/research/旧文件.pdf
```

命令行参数放在子命令前，文件路径放在 `ingest` 后。文件缺失、格式不支持、解析失败或没有有效文本均会报错。查询不存在的 Collection 会报错，空 Collection 返回无资料提示。

独立配置可从 `configs/collections/finance.example.ini` 或 `legal.example.ini` 复制为对应标识的 `<collection>.ini`。模板仅是配置示例，新增任意领域不需要修改核心代码。CLI 与网页文档清单分别管理，CLI 文件通过原路径执行删除。

## 支持格式

| 格式 | 解析方式与边界 |
| --- | --- |
| PDF | PyMuPDF 逐页提取，无文本页面使用已有 RapidOCR，无法提取有效文本时报错 |
| DOCX | 段落和表格文本 |
| DOC | LibreOffice 转 DOCX，或 Windows 上通过 PowerShell COM 调用已安装的 Microsoft Word |
| XLSX、XLSM | openpyxl，按工作表提取行列，宏不执行，公式保留表达式，不负责重新计算 |
| XLS | xlrd，按工作表提取行列 |
| CSV、TSV、TXT、Markdown | UTF-8，失败后尝试 GB18030 |
| PPTX | 按幻灯片提取文本框 |
| XMind | ZIP 中的新版 content.json 和旧版 content.xml，保留主题层次路径 |
| FreeMind `.mm`、OPML | 提取节点与父子路径 |
| PNG、JPG、JPEG | RapidOCR |

DOC 依赖外部转换软件，缺失时给出错误。LibreOffice 路径可设置 `RAG_OFFICE_CONVERTER`。加密文件、损坏文件、MindManager 等其他厂商的专有脑图格式尚未支持，应先导出为 XMind、FreeMind、OPML 或 PDF。脑图提取以节点标题为主，附件、布局和部分富文本备注尚未提取。

## HTTP 使用

客户端使用受控上传接口，禁止通过接口读取任意服务器路径。先通过网页创建知识库，或调用创建接口。

```powershell
$body = @{id='research';name='科研资料';domain='科研';instructions='引用资料来源'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8010/api/knowledge-bases -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
curl.exe -F "file=@documents/research/资料.xlsx" "http://127.0.0.1:8010/api/v1/documents/ingest?collection=research"
$question = @{collection='research';question='请概括这份资料';top_k=5} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8010/api/v1/rag/query -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($question))
```

入库响应包含 `success`、`collection`、`document_id`、`chunk_count`。问答响应包含 `answer`、`collection`、`sources`，每条来源包含文件名、来源路径、页码或逻辑位置和 Chunk ID。原 `/api/knowledge-bases/{id}/chat` SSE 流式接口继续供 Vue 页面使用。

## 索引版本和数据保护

文件身份按 CLI 源路径或网页上传文件名确定，同一身份更新后切换到新 Chunk 集合。相同内容重复导入使用稳定 Chunk ID。每个 Collection 使用进程间文件锁，完整写入后原子切换 `.runtime/indexes/<集合哈希>.json`。旧数据使用现有模式读取，第一次更新时建立基线清单。

替换和删除采用逻辑停用，旧版本物理向量保留以便回退，检索只使用有效 ID。切换前的清单保存在 `.previous.json`，发生故障可停止服务后恢复对应 JSON 清单，再启动服务。清单与 Milvus 必须共同备份。上传原文件版本也保留在 `.runtime/web/uploads`。当前未实现自动清理旧向量，长期使用需要规划存储清理。

## 自动化测试

```powershell
python -m unittest discover -s tests -v
$env:RAG_INTEGRATION = '1'
python -m unittest discover -s tests -v
```

默认运行不依赖远端模型的单元测试，Milvus 集成测试需开启环境变量并启动 Milvus。测试使用确定性 Embedding 和重排器验证真实持久化与检索隔离，临时 Collection 会在结束后清理。部分旧 Conda 环境需沿用 `run_api.py` 的包搜索顺序，避免用户级 Python 包覆盖环境依赖。

详细架构、配置、变更与测试记录见 `docs/architecture.md`、`docs/configuration.md`、`docs/refactoring-report.md`。

