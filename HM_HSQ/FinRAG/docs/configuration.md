# 配置说明

现有 INI 格式继续使用，避免新增配置框架。

优先级为显式 Collection 参数、RAG_COLLECTION、config.ini 默认 Collection。确定标识后，将 `configs/collections/<标识>.ini` 叠加在指定配置文件同级目录的基础配置上。配置中的相对文档和模型路径以基础配置文件目录为基准。切换配置后应重新启动 API 进程。

| 配置 | 用途 |
| --- | --- |
| rag.knowledge_base | 默认 Collection 标识，允许字母、数字、下划线和连字符 |
| rag.domain / instructions | 领域名称及回答要求，核心不依赖其具体值 |
| rag.document_directory | 知识库默认资料目录，CLI 仍要求明确传入实际路径 |
| milvus.host / port / database_name | 原 Milvus 服务连接 |
| models.embedding / reranker | 本地模型路径，API 按路径组合共享模型 |
| retrieval.parent_chunk_size / child_chunk_size / chunk_overlap | 父子分块参数，满足 0 ≤ overlap < child ≤ parent ≤ 8000 |
| retrieval.retrieval_k / candidate_m | 检索候选数及最终父块数 |
| retrieval.max_context_tokens | 检索上下文预算，128 至 16000，默认 3000 |
| retrieval.min_rerank_score | 原始重排模型分数阈值，默认 -100 保留原有召回行为 |
| llm.model / base_url | OpenAI 兼容模型服务参数 |

`RAG_API_KEY`、`DASHSCOPE_API_KEY`、`RAG_BASE_URL`、`RAG_LLM_MODEL` 覆盖对应模型配置。`RAG_PARENT_CHUNK_SIZE`、`RAG_CHILD_CHUNK_SIZE`、`RAG_CHUNK_OVERLAP`、`RAG_RETRIEVAL_K`、`RAG_CANDIDATE_M` 覆盖分块和检索参数。API Key 建议仅设置环境变量，已有配置密钥保持兼容。`.env.example` 是变量示例，项目不会自动读取 `.env`。

API 只接受受控文件上传，不提供服务器任意路径读取接口。知识库标识经过模式校验，上传文件名去除目录部分。XMind 展开数据总大小限制为 100 MB，XML 拒绝 DTD 与实体声明。DOC 的转换超时为 120 秒，Word 宏执行被禁用。

同一 Collection 必须使用兼容的 Embedding 模型。清单记录模型路径，路径变化会要求新建 Collection 重建索引。保留旧向量库和清单即可回退，禁止把新模型向量直接写入旧语义空间。
